"""
Capacity-aware NIM EndpointManager.

Every endpoint is a finite compute resource with:
  - max concurrent requests
  - health / latency / TTFT / TPS / failure metrics
  - cool-down and rate-limit state
  - estimated queue time

Dispatchers MUST acquire a lease only when ``active < max_concurrent``.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import httpx
from openai import OpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CV = threading.Condition(_LOCK)
_ENDPOINTS: List["NimEndpoint"] = []
_LOADED = False


@dataclass
class NimEndpoint:
    id: str
    api_key: str
    base_url: str
    roles: Set[str] = field(default_factory=lambda: {"map", "compile", "embed", "any"})
    client: Optional[OpenAI] = None
    max_concurrent: int = 3
    active: int = 0
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    latency_ema_ms: float = 1500.0
    ttft_ema_ms: float = 800.0
    tps_ema: float = 20.0
    cool_until: float = 0.0
    rate_limited_until: float = 0.0

    @property
    def healthy(self) -> bool:
        now = time.monotonic()
        return now >= self.cool_until and now >= self.rate_limited_until

    @property
    def available_slots(self) -> int:
        if not self.healthy or self.client is None:
            return 0
        return max(0, int(self.max_concurrent) - int(self.active))

    @property
    def success_rate(self) -> float:
        if self.total_calls <= 0:
            return 1.0
        return max(0.0, min(1.0, self.successes / float(self.total_calls)))

    @property
    def failure_rate(self) -> float:
        return 1.0 - self.success_rate

    @property
    def estimated_queue_time_sec(self) -> float:
        """Rough wait if at capacity: active * avg_latency / max_concurrent."""
        if self.available_slots > 0:
            return 0.0
        lat_s = max(0.2, self.latency_ema_ms / 1000.0)
        return lat_s * (self.active / max(1, self.max_concurrent))

    def health_score(self) -> float:
        """Lower is better. Cooling / rate-limited → infinity."""
        if not self.healthy:
            return 1e9
        q = min(1.0, self.active / max(1.0, float(self.max_concurrent)))
        ttft = min(1.0, self.ttft_ema_ms / 8000.0)
        tps_bad = min(1.0, max(0.0, 1.0 - (self.tps_ema / 40.0)))
        return (
            0.45 * q
            + 0.25 * ttft
            + 0.15 * tps_bad
            + 0.15 * self.failure_rate
        )

    def selection_key(self) -> tuple:
        """Least active → lowest latency → best health."""
        return (
            self.active,
            self.latency_ema_ms,
            self.health_score(),
        )


@dataclass
class EndpointLease:
    endpoint_id: str
    client: OpenAI
    role: str


def _parse_roles(raw: str) -> Set[str]:
    parts = {p.strip().lower() for p in (raw or "").split(",") if p.strip()}
    return parts or {"map", "compile", "embed", "any"}


def _default_max_concurrent() -> int:
    return max(1, int(getattr(settings, "NIM_ENDPOINT_MAX_CONCURRENT", 3) or 3))


def _collect_endpoint_specs() -> List[Dict[str, str]]:
    specs: List[Dict[str, str]] = []
    primary_key = (getattr(settings, "NVIDIA_API_KEY", None) or "").strip()
    primary_url = (
        getattr(settings, "NVIDIA_BASE_URL", None) or "https://integrate.api.nvidia.com/v1"
    ).strip()
    if primary_key:
        specs.append(
            {
                "id": "endpoint-1",
                "api_key": primary_key,
                "base_url": primary_url,
                "roles": getattr(settings, "NIM_ENDPOINT_1_ROLES", "map,compile,embed,any")
                or "map,compile,embed,any",
            }
        )

    for i in (2, 3, 4, 5):
        key = (
            getattr(settings, f"NIM_ENDPOINT_{i}_API_KEY", None)
            or getattr(settings, f"NVIDIA_API_KEY_{i}", None)
            or ""
        ).strip()
        if not key:
            continue
        url = (
            getattr(settings, f"NIM_ENDPOINT_{i}_BASE_URL", None)
            or getattr(settings, f"NVIDIA_BASE_URL_{i}", None)
            or primary_url
        ).strip()
        roles = getattr(settings, f"NIM_ENDPOINT_{i}_ROLES", None) or "map,compile,embed,any"
        specs.append(
            {
                "id": f"endpoint-{i}",
                "api_key": key,
                "base_url": url,
                "roles": str(roles),
            }
        )

    csv = (getattr(settings, "NIM_API_KEYS", None) or "").strip()
    if csv:
        for j, key in enumerate(csv.split(","), start=1):
            key = key.strip()
            if not key:
                continue
            if any(s["api_key"] == key for s in specs):
                continue
            specs.append(
                {
                    "id": f"endpoint-csv-{j}",
                    "api_key": key,
                    "base_url": primary_url,
                    "roles": "map,compile,embed,any",
                }
            )
    return specs


def load_endpoint_pool() -> List[NimEndpoint]:
    """(Re)build the pool from settings. Safe to call multiple times."""
    global _ENDPOINTS, _LOADED
    timeout_read = float(
        getattr(settings, "NIM_HARD_TIMEOUT_SEC", None)
        or getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 90.0)
        or 90.0
    )
    timeout_connect = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 15.0) or 15.0)
    timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
    max_retries = int(getattr(settings, "NIM_SDK_MAX_RETRIES", 0) or 0)
    max_conc = _default_max_concurrent()

    endpoints: List[NimEndpoint] = []
    for spec in _collect_endpoint_specs():
        try:
            client = OpenAI(
                api_key=spec["api_key"],
                base_url=spec["base_url"],
                timeout=timeout,
                max_retries=max_retries,
            )
            ep = NimEndpoint(
                id=spec["id"],
                api_key=spec["api_key"],
                base_url=spec["base_url"],
                roles=_parse_roles(spec.get("roles") or ""),
                client=client,
                max_concurrent=max_conc,
            )
            endpoints.append(ep)
            log.info(
                "NIM endpoint ready id=%s url=%s roles=%s max_concurrent=%s",
                ep.id,
                ep.base_url,
                sorted(ep.roles),
                ep.max_concurrent,
            )
        except Exception as e:
            log.error("Failed to init NIM endpoint %s: %s", spec.get("id"), e)

    with _CV:
        _ENDPOINTS = endpoints
        _LOADED = True
        _CV.notify_all()
    if not endpoints:
        log.warning("NIM endpoint pool is empty — set NVIDIA_API_KEY")
    else:
        log.info(
            "NIM endpoint pool size=%s total_capacity=%s",
            len(endpoints),
            len(endpoints) * max_conc,
        )
    return list(endpoints)


def ensure_pool_loaded() -> None:
    if not _LOADED:
        load_endpoint_pool()


def endpoint_count() -> int:
    ensure_pool_loaded()
    with _LOCK:
        return len(_ENDPOINTS)


def total_capacity(*, role: str = "any") -> int:
    ensure_pool_loaded()
    role = (role or "any").lower()
    with _LOCK:
        n = 0
        for e in _ENDPOINTS:
            if e.client is None:
                continue
            if role != "any" and role not in e.roles and "any" not in e.roles:
                continue
            n += int(e.max_concurrent)
        return n


def available_capacity(*, role: str = "any") -> int:
    ensure_pool_loaded()
    role = (role or "any").lower()
    with _LOCK:
        n = 0
        for e in _ENDPOINTS:
            if role != "any" and role not in e.roles and "any" not in e.roles:
                continue
            n += e.available_slots
        return n


def pool_snapshot() -> List[Dict[str, Any]]:
    ensure_pool_loaded()
    with _LOCK:
        return [
            {
                "id": e.id,
                "base_url": e.base_url,
                "roles": sorted(e.roles),
                "active": e.active,
                "max_concurrent": e.max_concurrent,
                "available_slots": e.available_slots,
                "total_calls": e.total_calls,
                "successes": e.successes,
                "failures": e.failures,
                "timeouts": e.timeouts,
                "rate_limits": e.rate_limits,
                "latency_ema_ms": round(e.latency_ema_ms, 1),
                "ttft_ema_ms": round(e.ttft_ema_ms, 1),
                "tps_ema": round(e.tps_ema, 2),
                "success_rate": round(e.success_rate, 4),
                "failure_rate": round(e.failure_rate, 4),
                "health_score": round(e.health_score(), 4),
                "healthy": e.healthy,
                "cooling": time.monotonic() < e.cool_until,
                "rate_limited": time.monotonic() < e.rate_limited_until,
                "estimated_queue_time_sec": round(e.estimated_queue_time_sec, 2),
            }
            for e in _ENDPOINTS
        ]


def scheduler_snapshot() -> Dict[str, Any]:
    snaps = pool_snapshot()
    active = sum(int(s["active"]) for s in snaps)
    capacity = sum(int(s["max_concurrent"]) for s in snaps)
    return {
        "endpoints": snaps,
        "endpoint_count": len(snaps),
        "active_requests": active,
        "total_capacity": capacity,
        "available_slots": max(0, capacity - active),
        "utilization": round(active / capacity, 4) if capacity else 0.0,
        "avg_latency_ms": round(
            sum(float(s["latency_ema_ms"]) for s in snaps) / max(1, len(snaps)), 1
        ),
        "avg_ttft_ms": round(
            sum(float(s["ttft_ema_ms"]) for s in snaps) / max(1, len(snaps)), 1
        ),
    }


def _candidates(
    role: str,
    *,
    exclude_ids: Optional[Set[str]] = None,
    require_capacity: bool = True,
) -> List[NimEndpoint]:
    role = (role or "any").lower()
    exclude_ids = exclude_ids or set()
    out: List[NimEndpoint] = []
    for e in _ENDPOINTS:
        if e.client is None or e.id in exclude_ids:
            continue
        if role != "any" and role not in e.roles and "any" not in e.roles:
            continue
        if not e.healthy:
            continue
        if require_capacity and e.available_slots <= 0:
            continue
        out.append(e)
    return out


def _pick(candidates: List[NimEndpoint]) -> Optional[NimEndpoint]:
    if not candidates:
        return None
    strategy = str(getattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load") or "least_load")
    if strategy == "round_robin":
        candidates = sorted(candidates, key=lambda e: (e.total_calls, e.active))
        return candidates[0]
    # least-load: active → latency → health (never random)
    candidates = sorted(candidates, key=lambda e: e.selection_key())
    return candidates[0]


def acquire_endpoint(
    *,
    role: str = "any",
    prefer_id: Optional[str] = None,
    exclude_ids: Optional[Set[str]] = None,
    block: bool = True,
    timeout: Optional[float] = None,
) -> Optional[EndpointLease]:
    """
    Reserve a capacity slot on the best healthy endpoint.

    When all endpoints are at ``max_concurrent``, blocks (back-pressure) until
    a slot frees or ``timeout`` elapses.
    """
    ensure_pool_loaded()
    role = (role or "any").lower()
    exclude_ids = set(exclude_ids or ())
    if timeout is None:
        timeout = float(getattr(settings, "NIM_ENDPOINT_ACQUIRE_TIMEOUT_SEC", 120.0) or 120.0)
    deadline = time.monotonic() + max(0.0, float(timeout))

    with _CV:
        while True:
            if not _ENDPOINTS:
                return None

            if prefer_id:
                for e in _ENDPOINTS:
                    if (
                        e.id == prefer_id
                        and e.client is not None
                        and e.id not in exclude_ids
                        and e.healthy
                        and e.available_slots > 0
                    ):
                        e.active += 1
                        return EndpointLease(endpoint_id=e.id, client=e.client, role=role)

            chosen = _pick(_candidates(role, exclude_ids=exclude_ids, require_capacity=True))
            if chosen is None and not exclude_ids:
                # No capacity among role-matched; try any healthy with capacity
                chosen = _pick(_candidates("any", exclude_ids=exclude_ids, require_capacity=True))

            if chosen is not None:
                chosen.active += 1
                return EndpointLease(
                    endpoint_id=chosen.id, client=chosen.client, role=role
                )

            if not block:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            _CV.wait(timeout=min(0.5, remaining))


def release_endpoint(
    lease: Optional[EndpointLease],
    *,
    ok: bool,
    latency_ms: float = 0.0,
    ttft_ms: float = 0.0,
    tokens: int = 0,
    rate_limited: bool = False,
    timed_out: bool = False,
) -> None:
    if lease is None:
        return
    with _CV:
        for e in _ENDPOINTS:
            if e.id != lease.endpoint_id:
                continue
            e.active = max(0, e.active - 1)
            e.total_calls += 1
            if latency_ms > 0:
                e.latency_ema_ms = 0.8 * e.latency_ema_ms + 0.2 * float(latency_ms)
            if ttft_ms > 0:
                e.ttft_ema_ms = 0.8 * e.ttft_ema_ms + 0.2 * float(ttft_ms)
            if tokens > 0 and latency_ms > 0:
                tps = tokens / max(0.05, latency_ms / 1000.0)
                e.tps_ema = 0.8 * e.tps_ema + 0.2 * tps
            if ok:
                e.successes += 1
            else:
                e.failures += 1
                cool = float(getattr(settings, "NIM_ENDPOINT_COOLDOWN_SEC", 8.0) or 8.0)
                e.cool_until = max(e.cool_until, time.monotonic() + cool)
            if timed_out:
                e.timeouts += 1
            if rate_limited:
                e.rate_limits += 1
                cool = float(
                    getattr(settings, "NIM_ENDPOINT_RATELIMIT_COOLDOWN_SEC", 20.0) or 20.0
                )
                e.rate_limited_until = max(e.rate_limited_until, time.monotonic() + cool)
                e.cool_until = max(e.cool_until, e.rate_limited_until)
            _CV.notify_all()
            return


def primary_client() -> Optional[OpenAI]:
    ensure_pool_loaded()
    with _LOCK:
        for e in _ENDPOINTS:
            if e.client is not None:
                return e.client
    return None
