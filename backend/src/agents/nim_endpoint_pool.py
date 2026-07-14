"""
Multi-NIM endpoint pool with least-load scheduling.

Loads NVIDIA_API_KEY (+ optional NIM_ENDPOINT_2/3_*) into independent OpenAI
clients and assigns each request to the healthiest endpoint.

Score (lower is better):
  0.4 * normalized_queue + 0.3 * normalized_ttft
  + 0.2 * (1 - normalized_tps) + 0.1 * failure_rate
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
_ENDPOINTS: List["NimEndpoint"] = []
_LOADED = False


@dataclass
class NimEndpoint:
    id: str
    api_key: str
    base_url: str
    roles: Set[str] = field(default_factory=lambda: {"map", "compile", "embed", "any"})
    client: Optional[OpenAI] = None
    active: int = 0
    total_calls: int = 0
    failures: int = 0
    rate_limits: int = 0
    latency_ema_ms: float = 1500.0
    cool_until: float = 0.0

    def health_score(self) -> float:
        now = time.monotonic()
        if now < self.cool_until:
            return 1e9
        # Normalize roughly: queue 0..16 → 0..1, latency 0..8s → 0..1
        q = min(1.0, self.active / 16.0)
        ttft = min(1.0, self.latency_ema_ms / 8000.0)
        # TPS proxy: inverse of latency
        tps_bad = ttft
        fail_rate = 0.0
        if self.total_calls > 0:
            fail_rate = min(1.0, self.failures / float(self.total_calls))
        return 0.4 * q + 0.3 * ttft + 0.2 * tps_bad + 0.1 * fail_rate


@dataclass
class EndpointLease:
    endpoint_id: str
    client: OpenAI
    role: str


def _parse_roles(raw: str) -> Set[str]:
    parts = {p.strip().lower() for p in (raw or "").split(",") if p.strip()}
    return parts or {"map", "compile", "embed", "any"}


def _collect_endpoint_specs() -> List[Dict[str, str]]:
    """Build endpoint specs from env/settings (primary + numbered peers)."""
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

    # Comma-separated overflow: NIM_API_KEYS=k1,k2,k3 (same base URL)
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
    timeout_read = float(getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 90.0) or 90.0)
    timeout_connect = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 15.0) or 15.0)
    timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
    max_retries = int(getattr(settings, "NIM_SDK_MAX_RETRIES", 0) or 0)

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
            )
            endpoints.append(ep)
            log.info(
                "NIM endpoint ready id=%s url=%s roles=%s",
                ep.id,
                ep.base_url,
                sorted(ep.roles),
            )
        except Exception as e:
            log.error("Failed to init NIM endpoint %s: %s", spec.get("id"), e)

    with _LOCK:
        _ENDPOINTS = endpoints
        _LOADED = True
    if not endpoints:
        log.warning("NIM endpoint pool is empty — set NVIDIA_API_KEY")
    else:
        log.info("NIM endpoint pool size=%s", len(endpoints))
    return list(endpoints)


def ensure_pool_loaded() -> None:
    if not _LOADED:
        load_endpoint_pool()


def endpoint_count() -> int:
    ensure_pool_loaded()
    with _LOCK:
        return len(_ENDPOINTS)


def pool_snapshot() -> List[Dict[str, Any]]:
    ensure_pool_loaded()
    with _LOCK:
        return [
            {
                "id": e.id,
                "base_url": e.base_url,
                "roles": sorted(e.roles),
                "active": e.active,
                "total_calls": e.total_calls,
                "failures": e.failures,
                "rate_limits": e.rate_limits,
                "latency_ema_ms": round(e.latency_ema_ms, 1),
                "health_score": round(e.health_score(), 4),
                "cooling": time.monotonic() < e.cool_until,
            }
            for e in _ENDPOINTS
        ]


def acquire_endpoint(*, role: str = "any", prefer_id: Optional[str] = None) -> Optional[EndpointLease]:
    """Pick the healthiest endpoint that supports ``role`` and bump active count."""
    ensure_pool_loaded()
    role = (role or "any").lower()
    with _LOCK:
        if not _ENDPOINTS:
            return None
        candidates = [
            e
            for e in _ENDPOINTS
            if e.client is not None
            and (role in e.roles or "any" in e.roles or role == "any")
        ]
        if not candidates:
            candidates = [e for e in _ENDPOINTS if e.client is not None]
        if not candidates:
            return None
        if prefer_id:
            for e in candidates:
                if e.id == prefer_id and time.monotonic() >= e.cool_until:
                    e.active += 1
                    return EndpointLease(endpoint_id=e.id, client=e.client, role=role)
        strategy = str(getattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load") or "least_load")
        if strategy == "round_robin":
            # lowest total_calls among non-cooling
            live = [e for e in candidates if time.monotonic() >= e.cool_until] or candidates
            live.sort(key=lambda e: (e.total_calls, e.active))
            chosen = live[0]
        else:
            live = [e for e in candidates if time.monotonic() >= e.cool_until] or candidates
            live.sort(key=lambda e: e.health_score())
            chosen = live[0]
        chosen.active += 1
        return EndpointLease(endpoint_id=chosen.id, client=chosen.client, role=role)


def release_endpoint(
    lease: Optional[EndpointLease],
    *,
    ok: bool,
    latency_ms: float = 0.0,
    rate_limited: bool = False,
) -> None:
    if lease is None:
        return
    with _LOCK:
        for e in _ENDPOINTS:
            if e.id != lease.endpoint_id:
                continue
            e.active = max(0, e.active - 1)
            e.total_calls += 1
            if latency_ms > 0:
                e.latency_ema_ms = 0.8 * e.latency_ema_ms + 0.2 * float(latency_ms)
            if not ok:
                e.failures += 1
                # Short cool-down so other endpoints absorb load
                cool = float(getattr(settings, "NIM_ENDPOINT_COOLDOWN_SEC", 8.0) or 8.0)
                e.cool_until = max(e.cool_until, time.monotonic() + cool)
            if rate_limited:
                e.rate_limits += 1
                cool = float(getattr(settings, "NIM_ENDPOINT_RATELIMIT_COOLDOWN_SEC", 20.0) or 20.0)
                e.cool_until = max(e.cool_until, time.monotonic() + cool)
            return


def primary_client() -> Optional[OpenAI]:
    ensure_pool_loaded()
    with _LOCK:
        for e in _ENDPOINTS:
            if e.client is not None:
                return e.client
    return None
