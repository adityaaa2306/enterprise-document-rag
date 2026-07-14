"""
Capacity-aware pull-based execution scheduler.

Tasks flow: Queue → Scheduler (capacity gate) → Worker → Endpoint → Complete.

Workers pull work. Endpoints advertise capacity. Map never submit-all-fires.
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from src.core.config import settings
from src.core.priority_queue import (
    PRIORITY_MAP,
    PriorityWorkQueue,
    priority_for_kind,
)

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class TaskProgress:
    """Honest progress: completed ≠ submitted."""

    submitted: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    retrying: int = 0
    total: int = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "submitted": self.submitted,
            "queued": self.queued,
            "running": self.running,
            "completed": self.completed,
            "failed": self.failed,
            "retrying": self.retrying,
            "total": self.total,
        }

    def message(self, prefix: str = "Summarizing") -> str:
        return (
            f"{prefix}... completed {self.completed}/{self.total} "
            f"(running {self.running}, queued {self.queued}, "
            f"failed {self.failed}, retrying {self.retrying})"
        )


@dataclass
class SchedulerMetrics:
    queue_wait_ms_sum: float = 0.0
    queue_wait_n: int = 0
    timeouts: int = 0
    retries: int = 0
    empty_retries: int = 0
    soft_ttft_cancels: int = 0
    chunks_done: int = 0
    wall_ms: float = 0.0

    def record_wait(self, ms: float) -> None:
        self.queue_wait_ms_sum += max(0.0, ms)
        self.queue_wait_n += 1

    def to_dict(self) -> Dict[str, Any]:
        avg_wait = (
            self.queue_wait_ms_sum / self.queue_wait_n if self.queue_wait_n else 0.0
        )
        cps = (
            (self.chunks_done / (self.wall_ms / 1000.0)) if self.wall_ms > 0 else 0.0
        )
        return {
            "avg_queue_wait_ms": round(avg_wait, 1),
            "timeouts": self.timeouts,
            "retries": self.retries,
            "empty_retries": self.empty_retries,
            "soft_ttft_cancels": self.soft_ttft_cancels,
            "chunks_done": self.chunks_done,
            "wall_ms": round(self.wall_ms, 1),
            "chunks_per_sec": round(cps, 3),
        }


@dataclass
class _WorkItem(Generic[T]):
    payload: T
    enqueued_at: float
    attempt: int = 0
    priority: int = PRIORITY_MAP


def _endpoint_capacity(role: str) -> int:
    try:
        from src.agents import nim_endpoint_pool as pool

        return max(1, int(pool.total_capacity(role=role)))
    except Exception:
        return max(1, int(getattr(settings, "MAP_MAX_WORKERS", 4) or 4))


def run_capacity_pool(
    items: List[T],
    worker_fn: Callable[[T], R],
    *,
    role: str = "map",
    kind: str = "map",
    max_workers: Optional[int] = None,
    hard_timeout_sec: Optional[float] = None,
    max_attempts: int = 2,
    is_success: Optional[Callable[[R], bool]] = None,
    on_progress: Optional[Callable[[TaskProgress, SchedulerMetrics], None]] = None,
    progress_interval_sec: float = 2.0,
) -> tuple[List[Optional[R]], TaskProgress, SchedulerMetrics]:
    """
    Pull-based capacity-aware execution.

    - Enqueues all items (does NOT fire them at NIM)
    - Worker count capped to endpoint capacity
    - Each worker pulls one task, runs it, then pulls the next
    - Hard timeout abandons a single attempt (not 390s multi-model walls)
    - Failed / empty results retry up to ``max_attempts`` (endpoint/model
      rotation happens inside the NIM call path)
    """
    total = len(items)
    progress = TaskProgress(submitted=total, queued=total, total=total)
    metrics = SchedulerMetrics()
    if total == 0:
        return [], progress, metrics

    if is_success is None:
        is_success = lambda _r: True  # noqa: E731

    hard_timeout_sec = float(
        hard_timeout_sec
        if hard_timeout_sec is not None
        else getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", None)
        or getattr(settings, "NIM_HARD_TIMEOUT_SEC", 90.0)
        or 90.0
    )
    capacity = _endpoint_capacity(role)
    if max_workers is None:
        if role == "compile":
            max_workers = int(settings.effective_compile_max_workers())
        else:
            max_workers = int(settings.effective_map_max_workers())
    workers = max(1, min(int(max_workers), capacity, total))
    priority = priority_for_kind(kind)
    capacity_sem = threading.Semaphore(capacity)

    queue: PriorityWorkQueue[_WorkItem[T]] = PriorityWorkQueue()
    for payload in items:
        queue.put(
            _WorkItem(payload=payload, enqueued_at=time.perf_counter(), priority=priority),
            priority,
        )

    results: Dict[Any, Optional[R]] = {}
    lock = threading.Lock()
    t0 = time.perf_counter()
    last_progress = [0.0]

    log.info(
        "Scheduler start role=%s kind=%s items=%s workers=%s capacity=%s hard_timeout=%.0fs",
        role,
        kind,
        total,
        workers,
        capacity,
        hard_timeout_sec,
    )

    def _emit(force: bool = False) -> None:
        now = time.perf_counter()
        if not force and (now - last_progress[0]) < progress_interval_sec:
            return
        last_progress[0] = now
        if on_progress:
            try:
                on_progress(progress, metrics)
            except Exception:
                pass

    def _key(payload: T) -> Any:
        if isinstance(payload, tuple) and payload:
            return payload[0]
        return id(payload)

    def _handle_result(item: _WorkItem[T], result: Optional[R], err: Optional[BaseException]) -> None:
        nonlocal progress
        key = _key(item.payload)
        ok = err is None and result is not None and is_success(result)
        with lock:
            progress.running = max(0, progress.running - 1)
            if ok:
                results[key] = result
                progress.completed += 1
                metrics.chunks_done += 1
            elif item.attempt + 1 < max_attempts:
                progress.retrying += 1
                metrics.retries += 1
                nxt = _WorkItem(
                    payload=item.payload,
                    enqueued_at=time.perf_counter(),
                    attempt=item.attempt + 1,
                    priority=item.priority,
                )
                progress.queued += 1
                queue.put(nxt, item.priority)
                progress.retrying = max(0, progress.retrying - 1)
            else:
                results[key] = result
                progress.failed += 1
                if err is not None:
                    metrics.timeouts += 1
        _emit(force=True)

    stop = threading.Event()

    def _worker() -> None:
        while not stop.is_set():
            item = queue.get(timeout=0.4)
            if item is None:
                with lock:
                    # Exit when nothing queued/running remains for this wave
                    if progress.queued <= 0 and progress.running <= 0:
                        return
                continue
            with lock:
                progress.queued = max(0, progress.queued - 1)
                progress.running += 1
            wait_ms = (time.perf_counter() - item.enqueued_at) * 1000.0
            metrics.record_wait(wait_ms)
            _emit()

            result: Optional[R] = None
            err: Optional[BaseException] = None
            # Global concurrency cap (= endpoint capacity). Inner NIM acquire
            # also enforces per-endpoint max_concurrent (back-pressure).
            acquired = capacity_sem.acquire(timeout=hard_timeout_sec)
            if not acquired:
                with lock:
                    progress.running = max(0, progress.running - 1)
                    progress.queued += 1
                    metrics.retries += 1
                queue.put(
                    _WorkItem(
                        payload=item.payload,
                        enqueued_at=time.perf_counter(),
                        attempt=item.attempt,
                        priority=item.priority,
                    ),
                    item.priority,
                )
                continue
            one = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                fut = one.submit(worker_fn, item.payload)
                try:
                    result = fut.result(timeout=hard_timeout_sec)
                except concurrent.futures.TimeoutError as te:
                    err = te
                    metrics.timeouts += 1
                    log.warning(
                        "Scheduler hard-timeout after %.0fs role=%s attempt=%s",
                        hard_timeout_sec,
                        role,
                        item.attempt + 1,
                    )
            except Exception as e:
                err = e
            finally:
                # Never wait on a hung NIM thread (wait=True re-introduces 390s walls).
                try:
                    one.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    one.shutdown(wait=False)
                capacity_sem.release()

            _handle_result(item, result, err)

    threads = [
        threading.Thread(target=_worker, name=f"sched-{role}-{i}", daemon=True)
        for i in range(workers)
    ]
    for th in threads:
        th.start()

    # Wait until all items resolved
    while True:
        with lock:
            done = progress.completed + progress.failed
            if done >= total and progress.queued <= 0 and progress.running <= 0:
                break
        _emit()
        time.sleep(0.25)
        # Safety: if workers died with work left, break after long stall
        if (time.perf_counter() - t0) > hard_timeout_sec * max(2, total) + 60:
            log.error("Scheduler safety wall hit role=%s total=%s", role, total)
            break

    stop.set()
    queue.close()
    for th in threads:
        th.join(timeout=2.0)

    metrics.wall_ms = (time.perf_counter() - t0) * 1000.0
    _emit(force=True)

    # Preserve input order when payloads are (idx, ...)
    ordered: List[Optional[R]] = []
    if items and isinstance(items[0], tuple):
        by_idx = results
        max_idx = max((p[0] for p in items if isinstance(p, tuple)), default=-1)
        ordered = [None] * (max_idx + 1)
        for k, v in by_idx.items():
            if isinstance(k, int) and 0 <= k <= max_idx:
                ordered[k] = v
    else:
        ordered = [results.get(_key(p)) for p in items]

    return ordered, progress, metrics


def map_progress_partial(progress: TaskProgress, metrics: SchedulerMetrics) -> Dict[str, Any]:
    """Blob for JOB_STATUSES[job_id]['partial']."""
    try:
        from src.agents import nim_endpoint_pool as pool

        sched = pool.scheduler_snapshot()
    except Exception:
        sched = {}
    return {
        "chunks_done": progress.completed,
        "chunks_total": progress.total,
        "scheduler": {
            **progress.snapshot(),
            **metrics.to_dict(),
            "endpoints": sched,
        },
    }
