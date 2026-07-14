"""
Immutable / TTL caches for safe recomputation avoidance.

Cached artifacts never alter carbon equations or routing logic — they only
skip repeated I/O and tokenization of identical inputs.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, Optional, Tuple

_lock = threading.Lock()

# token_count cache: sha256(text) → int
_TOKEN_CACHE: Dict[str, int] = {}
_TOKEN_CACHE_MAX = 50_000

# Electricity Maps: (zone_or_latlon_key) → (expires_at, payload)
_GRID_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_GRID_TTL_SEC = 300.0  # 5 minutes — intensity drifts slowly

# Carbon model constants (immutable per process)
_CARBON_CONSTANTS: Dict[str, Any] = {}


def document_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def get_token_count(text: str, *, estimator=None) -> int:
    """
    Cached token estimate. Default estimator matches chunking.service
    (len//4) so results are identical to uncached calls.
    """
    key = _text_key(text)
    with _lock:
        hit = _TOKEN_CACHE.get(key)
    if hit is not None:
        return hit
    if estimator is None:
        value = max(1, len(text or "") // 4)
    else:
        value = int(estimator(text))
    with _lock:
        if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
            # Drop arbitrary half to bound memory
            for k in list(_TOKEN_CACHE.keys())[: _TOKEN_CACHE_MAX // 2]:
                _TOKEN_CACHE.pop(k, None)
        _TOKEN_CACHE[key] = value
    return value


def grid_cache_key(
    *,
    zone: str = "",
    lat: float = 0.0,
    lon: float = 0.0,
) -> str:
    z = (zone or "").strip()
    if z:
        return f"zone:{z}"
    return f"latlon:{lat:.4f},{lon:.4f}"


def get_cached_grid_intensity(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _lock:
        entry = _GRID_CACHE.get(key)
        if not entry:
            return None
        expires, payload = entry
        if now >= expires:
            _GRID_CACHE.pop(key, None)
            return None
        return dict(payload)


def put_cached_grid_intensity(
    key: str,
    payload: Dict[str, Any],
    *,
    ttl_sec: Optional[float] = None,
) -> None:
    ttl = float(ttl_sec if ttl_sec is not None else _GRID_TTL_SEC)
    with _lock:
        _GRID_CACHE[key] = (time.time() + ttl, dict(payload))


def get_carbon_constant(name: str, default: Any = None) -> Any:
    with _lock:
        return _CARBON_CONSTANTS.get(name, default)


def set_carbon_constant(name: str, value: Any) -> None:
    with _lock:
        _CARBON_CONSTANTS[name] = value


def clear_perf_caches() -> None:
    """Test helper."""
    with _lock:
        _TOKEN_CACHE.clear()
        _GRID_CACHE.clear()
