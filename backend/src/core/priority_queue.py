"""Priority work queues for map / hierarchy / executive tasks."""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")

# Lower number = higher priority
PRIORITY_EXECUTIVE = 0
PRIORITY_REPAIR = 1
PRIORITY_CHAPTER = 2
PRIORITY_REGIONAL = 3
PRIORITY_MAP = 4
PRIORITY_INDEX = 5


@dataclass(order=True)
class PrioritizedItem(Generic[T]):
    priority: int
    seq: int
    item: T = field(compare=False)


class PriorityWorkQueue(Generic[T]):
    """Thread-safe min-heap priority queue."""

    def __init__(self) -> None:
        self._heap: List[PrioritizedItem[T]] = []
        self._cv = threading.Condition()
        self._seq = itertools.count()
        self._closed = False

    def put(self, item: T, priority: int = PRIORITY_MAP) -> None:
        with self._cv:
            if self._closed:
                raise RuntimeError("queue closed")
            heapq.heappush(
                self._heap, PrioritizedItem(int(priority), next(self._seq), item)
            )
            self._cv.notify()

    def get(self, timeout: Optional[float] = None) -> Optional[T]:
        with self._cv:
            if not self._heap and not self._closed:
                self._cv.wait(timeout=timeout)
            if not self._heap:
                return None
            return heapq.heappop(self._heap).item

    def qsize(self) -> int:
        with self._cv:
            return len(self._heap)

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()


def priority_for_kind(kind: str) -> int:
    k = (kind or "").lower()
    if k in ("executive", "final", "compile"):
        return PRIORITY_EXECUTIVE
    if k in ("repair", "branch_repair"):
        return PRIORITY_REPAIR
    if k == "chapter":
        return PRIORITY_CHAPTER
    if k == "regional":
        return PRIORITY_REGIONAL
    if k in ("index", "embed", "bm25"):
        return PRIORITY_INDEX
    return PRIORITY_MAP
