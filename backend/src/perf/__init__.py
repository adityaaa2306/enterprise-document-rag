"""
Production latency optimizations — execution only.

Does NOT change routing decisions, carbon equations, validation thresholds,
or dashboard metric formulas. Only concurrency, caching, batching, and I/O.
"""
from src.perf.cache import (
    document_content_hash,
    get_cached_grid_intensity,
    get_token_count,
    put_cached_grid_intensity,
)
from src.perf.prefetch import (
    cancel_embed_prefetch,
    get_embed_prefetch,
    start_embed_prefetch,
)
from src.perf.progress import (
    flush_progress,
    publish_lifecycle_progress,
    resolve_progress_message,
    set_progress_throttled,
)

__all__ = [
    "document_content_hash",
    "get_cached_grid_intensity",
    "put_cached_grid_intensity",
    "get_token_count",
    "start_embed_prefetch",
    "get_embed_prefetch",
    "cancel_embed_prefetch",
    "set_progress_throttled",
    "flush_progress",
    "publish_lifecycle_progress",
    "resolve_progress_message",
]
