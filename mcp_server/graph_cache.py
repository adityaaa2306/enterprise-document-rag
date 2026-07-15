"""LRU caches for repeated graph traversals / summaries."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Tunables
SEARCH_CACHE_SIZE = 256
PATH_CACHE_SIZE = 256
SUMMARY_CACHE_SIZE = 128


def clear_all_caches() -> None:
    for fn in _CACHE_FUNCS:
        fn.cache_clear()


_CACHE_FUNCS: list = []


def tracked_lru(maxsize: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        wrapped = lru_cache(maxsize=maxsize)(fn)
        _CACHE_FUNCS.append(wrapped)
        return wrapped  # type: ignore[return-value]

    return deco
