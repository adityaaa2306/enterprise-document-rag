"""
Joint model assignment for ready DAG nodes.

Scores available models within the CRE/router minimum tier using *live*
worker queue depth/load, live grid intensity, and rolling per-model latency
from recent calls — not static priors alone. Assignment can shift mid-job
as load or grid conditions change.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Sequence

from src.core.config import settings

log = logging.getLogger(__name__)

# Rolling latency window (ms) per model_id — shared across assigner calls in-process.
_LATENCY_LOCK = threading.Lock()
_MODEL_LATENCY_MS: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=32))
_GRID_CACHE: Dict[str, Any] = {"value": None, "at": 0.0}
_GRID_TTL_SEC = 30.0  # short TTL so mid-job spikes are visible


def record_model_latency(model_id: Optional[str], latency_ms: float) -> None:
    """Record a live observation for joint scheduling."""
    mid = (model_id or "").strip()
    if not mid or latency_ms is None:
        return
    try:
        ms = float(latency_ms)
    except (TypeError, ValueError):
        return
    if ms < 0:
        return
    with _LATENCY_LOCK:
        _MODEL_LATENCY_MS[mid].append(ms)


def rolling_latency_ms(model_id: Optional[str], default: float = 1800.0) -> float:
    mid = (model_id or "").strip()
    if not mid:
        return default
    with _LATENCY_LOCK:
        samples = list(_MODEL_LATENCY_MS.get(mid) or [])
    if not samples:
        return default
    return sum(samples) / len(samples)


def clear_latency_window() -> None:
    with _LATENCY_LOCK:
        _MODEL_LATENCY_MS.clear()


def _pool_load(state: Optional[dict] = None) -> float:
    """0–1 load from live endpoint pool / capacity workers / test overrides."""
    if state is not None:
        ov = state.get("_assigner_load_override")
        if ov is not None:
            try:
                return min(1.0, max(0.0, float(ov)))
            except (TypeError, ValueError):
                pass
        # Job-local queue depth from partial progress (live mid-job signal)
        try:
            from src.db import jobs as job_store

            jid = state.get("job_id")
            if jid:
                partial = (job_store.JOB_STATUSES.get(jid) or {}).get("partial") or {}
                busy = float(partial.get("workers_busy") or 0)
                total = float(partial.get("workers_total") or 0)
                rem = float(partial.get("remaining_tasks") or 0)
                if total > 0:
                    # Blend in-flight workers with backlog pressure
                    return min(1.0, max(busy / total, rem / max(total * 4.0, 1.0)))
        except Exception:
            pass
    try:
        from src.agents import nim_endpoint_pool as pool

        snap = pool.pool_snapshot() or []
        if not snap:
            return 0.5
        busy = 0
        cap = 0
        for e in snap:
            busy += int(e.get("in_flight") or e.get("busy") or 0)
            cap += int(e.get("max_concurrent") or e.get("capacity") or 1)
        if cap <= 0:
            return 0.5
        return min(1.0, busy / cap)
    except Exception:
        return 0.5


def refresh_live_grid_intensity(state: Optional[dict] = None) -> float:
    """
    Fetch current grid intensity (Electricity Maps) with a short TTL so
    mid-job spikes change subsequent assignments. Writes into state.features.
    """
    if state is not None:
        ov = state.get("_assigner_grid_override")
        if ov is not None:
            try:
                val = float(ov)
                feat = dict(state.get("features") or {})
                feat["grid_intensity"] = val
                feat["grid_intensity_source"] = "override"
                state["features"] = feat
                return val
            except (TypeError, ValueError):
                pass

    now = time.monotonic()
    cached = _GRID_CACHE.get("value")
    at = float(_GRID_CACHE.get("at") or 0.0)
    if cached is not None and (now - at) < _GRID_TTL_SEC:
        intensity = float(cached)
    else:
        intensity = float(getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700)
        source = "fallback_local"
        try:
            from src.carbon.electricity_maps import fetch_grid_carbon_intensity

            region = str(
                getattr(settings, "ELECTRICITY_MAPS_ZONE", None)
                or getattr(settings, "REGION_SCHEDULER_DEFAULT_REGION", "IN")
                or "IN"
            )
            # Normalize common names → ISO zones
            zone_map = {"india": "IN", "IN-NO": "IN", "us": "US-CAL-CISO"}
            region = zone_map.get(region.lower(), region)
            data = fetch_grid_carbon_intensity(zone=region) or {}
            raw = data.get("intensity_gco2_kwh") or data.get("carbon_intensity")
            if raw is not None:
                intensity = float(raw)
                source = str(data.get("source") or "electricity_maps")
        except Exception as e:
            log.debug("live grid fetch failed: %s", e)
        _GRID_CACHE["value"] = intensity
        _GRID_CACHE["at"] = now
        _GRID_CACHE["source"] = source

    if state is not None:
        feat = dict(state.get("features") or {})
        feat["grid_intensity"] = intensity
        feat["grid_intensity_source"] = _GRID_CACHE.get("source") or "live"
        state["features"] = feat
    return float(intensity)


def _grid_intensity(state: Optional[dict] = None) -> float:
    if state is not None and state.get("_assigner_grid_override") is not None:
        return refresh_live_grid_intensity(state)
    if state:
        feat = state.get("features") or {}
        # Prefer refreshing when stale / missing live source
        src = str(feat.get("grid_intensity_source") or "")
        if feat.get("grid_intensity") is not None and src in (
            "override",
            "electricity_maps",
            "live",
        ):
            # Still refresh on short TTL via cache
            return refresh_live_grid_intensity(state)
        if feat.get("grid_intensity") is not None and src == "static_prior":
            return float(feat["grid_intensity"])
    return refresh_live_grid_intensity(state)


def _tier_priors(tier: str) -> Dict[str, float]:
    t = (tier or "medium").lower()
    table = {
        "light": {"quality": 0.62, "latency_ms": 800.0, "carbon_g": 0.08},
        "medium": {"quality": 0.78, "latency_ms": 1800.0, "carbon_g": 0.22},
        "heavy": {"quality": 0.92, "latency_ms": 4500.0, "carbon_g": 0.55},
    }
    return table.get(t, table["medium"])


def assign_model_for_node(
    *,
    node_kind: str,
    min_tier: str,
    model_chain: Sequence[str],
    state: Optional[dict] = None,
    prefer_quality: bool = False,
) -> Dict[str, Any]:
    """
    Pick a model from model_chain using joint utility over live signals.

    Returns {model_id, tier, score, reasons, load, grid_intensity}.
    """
    chain = [m for m in (model_chain or []) if m]
    if not chain:
        return {"model_id": None, "tier": min_tier, "score": 0.0, "reasons": ["empty_chain"]}

    load = _pool_load(state)
    intensity = _grid_intensity(state)
    carbon_pressure = min(1.0, max(0.0, (intensity - 200.0) / 600.0))

    n = len(chain)
    best = None
    best_score = -1e9
    reasons_best: List[str] = []

    w_quality = 0.40 if prefer_quality or node_kind in ("executive", "final") else 0.30
    w_latency = 0.30  # live latency weighted higher than static priors alone
    w_carbon = 0.25
    w_load = 0.25

    for i, mid in enumerate(chain):
        frac = i / max(1, n - 1) if n > 1 else 0.0
        if min_tier == "heavy" or (prefer_quality and i == n - 1):
            priors = _tier_priors("heavy" if i == n - 1 else min_tier)
        elif min_tier == "light":
            priors = _tier_priors("light" if i == 0 else "medium")
        else:
            priors = _tier_priors("medium" if i == 0 else ("heavy" if frac > 0.66 else "medium"))

        live_lat = rolling_latency_ms(mid, default=priors["latency_ms"])
        load_penalty = load * frac
        carbon_penalty = carbon_pressure * (priors["carbon_g"] / 0.55)
        latency_penalty = live_lat / 5000.0
        quality = priors["quality"]

        score = (
            w_quality * quality
            - w_latency * latency_penalty
            - w_carbon * carbon_penalty
            - w_load * load_penalty
        )
        # Prefer earlier (usually cheaper/faster) models when busy or grid dirty
        if load > 0.55 or carbon_pressure > 0.55:
            score += 0.08 * (1.0 - frac)
        # Prefer later (higher quality) when load+grid are calm and quality wanted
        if prefer_quality and load < 0.35 and carbon_pressure < 0.45:
            score += 0.06 * frac

        if score > best_score:
            best_score = score
            best = mid
            reasons_best = [
                f"load={load:.2f}",
                f"grid={intensity:.0f}",
                f"live_lat_ms={live_lat:.0f}",
                f"quality={quality:.2f}",
                f"idx={i}/{n}",
            ]

    return {
        "model_id": best or chain[0],
        "tier": min_tier,
        "score": round(best_score, 4),
        "reasons": reasons_best,
        "chain": list(chain),
        "load": round(load, 4),
        "grid_intensity": round(intensity, 2),
    }


def chain_for_tier(tier: str) -> List[str]:
    t = (tier or "medium").lower()
    if t == "light":
        return list(settings.light_models())
    if t == "heavy":
        return list(settings.heavy_models())
    return list(settings.medium_models())
