"""
Per-model time-slice allocation inside a shared fallback-chain wall.

Problem this solves: primary models (e.g. ministral-14b) could consume the
entire COMPILE/MAP hard wall, starving designated fallbacks of any real budget.

Design:
- Allocate explicit slices (fractions of remaining wall) to each chain position.
- Guarantee every model (including the last fallback) a minimum slice when possible.
- Record slice usage + rolling reliability for telemetry / soft deprioritization.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)


def parse_slice_fractions(raw: Any, *, n: int) -> List[float]:
    """
    Parse CSV / list of fractions into ``n`` positive weights that sum to 1.0.

    If fewer fractions than models are given, the remainder is split evenly
    across the trailing positions. If more are given, extras are dropped.
    """
    vals: List[float] = []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        for p in parts:
            try:
                vals.append(float(p))
            except ValueError:
                continue
    elif isinstance(raw, (list, tuple)):
        for p in raw:
            try:
                vals.append(float(p))
            except (TypeError, ValueError):
                continue

    n = max(1, int(n))
    if not vals:
        return [1.0 / n] * n
    if len(vals) < n:
        rem = max(0.0, 1.0 - sum(v for v in vals if v > 0))
        trailing = n - len(vals)
        fill = rem / trailing if trailing and rem > 0 else (1.0 / n)
        vals = list(vals) + [fill] * trailing
    vals = vals[:n]
    # Clamp negatives, then renormalize.
    vals = [max(0.0, float(v)) for v in vals]
    s = sum(vals)
    if s <= 0:
        return [1.0 / n] * n
    return [v / s for v in vals]


def allocate_slices(
    n_models: int,
    total_sec: float,
    fractions: Sequence[float],
    *,
    min_slice_sec: float = 8.0,
) -> List[float]:
    """
    Allocate wall seconds to each model position.

    Ensures (when total allows) every position gets at least ``min_slice_sec``,
    then distributes the remainder by ``fractions``. If the wall is too small
    for all minima, scales minima down proportionally so the last model still
    gets a non-zero share.
    """
    n = max(1, int(n_models))
    total = max(0.5, float(total_sec))
    fracs = parse_slice_fractions(list(fractions) if fractions else None, n=n)
    min_s = max(0.5, float(min_slice_sec))

    if n * min_s > total:
        # Scale minima so every model still gets something.
        min_s = total / n

    base = [min_s] * n
    rem = total - sum(base)
    if rem > 0:
        for i in range(n):
            base[i] += rem * fracs[i]
    # Final normalize to exact total (float drift).
    s = sum(base)
    if s > 0 and abs(s - total) > 1e-6:
        base = [b * (total / s) for b in base]
    return [round(max(0.5, b), 3) for b in base]


@dataclass
class SliceAttempt:
    model_id: str
    position: int
    allocated_sec: float
    used_sec: float = 0.0
    outcome: str = "pending"  # success | timeout_slice | error | cancelled | skipped
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "position": self.position,
            "allocated_sec": round(self.allocated_sec, 3),
            "used_sec": round(self.used_sec, 3),
            "outcome": self.outcome,
            "error": (self.error or "")[:200] or None,
        }


@dataclass
class ChainSliceReport:
    role: str
    wall_sec: float
    fractions: List[float]
    attempts: List[SliceAttempt] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "wall_sec": round(self.wall_sec, 3),
            "fractions": self.fractions,
            "attempts": [a.to_dict() for a in self.attempts],
        }


class ModelReliabilityTracker:
    """
    Rolling per-model success / timeout / error counters.

    Soft deprioritization only activates when sample size + timeout rate clear
    configured thresholds — never from a single job.
    """

    def __init__(self, window: int = 50) -> None:
        self._window = max(5, int(window))
        self._lock = threading.Lock()
        # model_id -> deque of {"ok": bool, "timeout": bool, "ts": float}
        self._events: Dict[str, Deque[Dict[str, Any]]] = {}

    def record(
        self,
        model_id: str,
        *,
        ok: bool,
        timeout: bool = False,
        error: bool = False,
    ) -> None:
        mid = str(model_id or "").strip()
        if not mid:
            return
        with self._lock:
            q = self._events.setdefault(mid, deque(maxlen=self._window))
            q.append(
                {
                    "ok": bool(ok),
                    "timeout": bool(timeout),
                    "error": bool(error) and not ok,
                    "ts": time.time(),
                }
            )

    def stats(self, model_id: str) -> Dict[str, Any]:
        mid = str(model_id or "").strip()
        with self._lock:
            q = list(self._events.get(mid) or [])
        n = len(q)
        if n == 0:
            return {
                "model_id": mid,
                "n": 0,
                "success_rate": None,
                "timeout_rate": None,
                "error_rate": None,
            }
        ok_n = sum(1 for e in q if e.get("ok"))
        to_n = sum(1 for e in q if e.get("timeout"))
        err_n = sum(1 for e in q if e.get("error"))
        return {
            "model_id": mid,
            "n": n,
            "success_rate": round(ok_n / n, 4),
            "timeout_rate": round(to_n / n, 4),
            "error_rate": round(err_n / n, 4),
        }

    def all_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            keys = list(self._events.keys())
        return {k: self.stats(k) for k in keys}

    def soft_deprioritize_order(
        self,
        model_ids: Sequence[str],
        *,
        enabled: bool,
        timeout_rate_threshold: float,
        min_samples: int,
    ) -> List[str]:
        """
        Move sustained-timeout models later in the chain (never remove them).

        Requires ``enabled`` and enough samples above the timeout-rate threshold.
        """
        ordered = [m for m in model_ids if m]
        if not enabled or len(ordered) <= 1:
            return ordered
        keep: List[str] = []
        demote: List[str] = []
        for mid in ordered:
            st = self.stats(mid)
            n = int(st.get("n") or 0)
            rate = st.get("timeout_rate")
            if (
                n >= int(min_samples)
                and rate is not None
                and float(rate) >= float(timeout_rate_threshold)
            ):
                demote.append(mid)
                log.info(
                    "Soft-deprioritize model=%s timeout_rate=%.2f n=%s "
                    "(moving later in chain)",
                    mid,
                    rate,
                    n,
                )
            else:
                keep.append(mid)
        return keep + demote


_TRACKER: Optional[ModelReliabilityTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_reliability_tracker() -> ModelReliabilityTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            from src.core.config import settings

            window = int(getattr(settings, "MODEL_RELIABILITY_WINDOW", 50) or 50)
            _TRACKER = ModelReliabilityTracker(window=window)
        return _TRACKER


def reset_reliability_tracker_for_tests() -> None:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = None


def fractions_for_role(role: str) -> List[float]:
    from src.core.config import settings

    r = (role or "map").lower()
    if r == "compile":
        raw = getattr(settings, "COMPILE_CHAIN_SLICE_FRACTIONS", "0.40,0.35,0.25")
    else:
        raw = getattr(settings, "MAP_CHAIN_SLICE_FRACTIONS", "0.45,0.35,0.20")
    # Return raw list for logging; allocate_slices will parse for n.
    if isinstance(raw, str):
        return [
            float(p.strip())
            for p in raw.replace(";", ",").split(",")
            if p.strip()
        ] or [0.45, 0.35, 0.20]
    return list(raw) if raw else [0.45, 0.35, 0.20]


def plan_chain_slices(
    model_ids: Sequence[str],
    *,
    role: str,
    wall_sec: float,
) -> Tuple[List[str], List[float], ChainSliceReport]:
    """
    Optionally soft-reorder + allocate slices. Returns (ordered_ids, slices, report).
    """
    from src.core.config import settings

    tracker = get_reliability_tracker()
    ordered = tracker.soft_deprioritize_order(
        list(model_ids),
        enabled=bool(getattr(settings, "MODEL_RELIABILITY_SOFT_DEPRIORITIZE", False)),
        timeout_rate_threshold=float(
            getattr(settings, "MODEL_RELIABILITY_TIMEOUT_RATE_THRESHOLD", 0.55) or 0.55
        ),
        min_samples=int(getattr(settings, "MODEL_RELIABILITY_MIN_SAMPLES", 20) or 20),
    )
    fracs = fractions_for_role(role)
    min_slice = float(getattr(settings, "CHAIN_SLICE_MIN_SEC", 8.0) or 8.0)
    slices = allocate_slices(
        len(ordered) or 1,
        wall_sec,
        fracs,
        min_slice_sec=min_slice,
    )
    report = ChainSliceReport(
        role=role,
        wall_sec=float(wall_sec),
        fractions=parse_slice_fractions(fracs, n=max(1, len(ordered))),
    )
    for i, mid in enumerate(ordered):
        report.attempts.append(
            SliceAttempt(
                model_id=mid,
                position=i,
                allocated_sec=slices[i] if i < len(slices) else min_slice,
            )
        )
    return ordered, slices, report


def log_slice_report(report: ChainSliceReport) -> None:
    parts = [
        f"{a.model_id}@{a.position}:alloc={a.allocated_sec:.1f}s"
        f"/used={a.used_sec:.1f}s/{a.outcome}"
        for a in report.attempts
    ]
    log.info(
        "CHAIN_SLICE role=%s wall=%.1fs %s",
        report.role,
        report.wall_sec,
        " | ".join(parts) if parts else "(empty)",
    )
