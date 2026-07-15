"""
Capacity-aware pull-based execution scheduler.

Tasks flow: Queue → Scheduler (capacity gate) → Worker → Endpoint → Complete.

Workers pull work. Endpoints advertise capacity. Map never submit-all-fires.

Lifecycle (per chunk attempt) — every transition is logged at INFO as
``TASK_LIFECYCLE`` so hangs can be pinpointed:

  QUEUED → ASSIGNED → ENDPOINT_SELECTED → HTTP_REQUEST_STARTED →
  TTFT_RECEIVED → TOKEN_STREAM_STARTED → RESPONSE_RECEIVED →
  SUMMARY_PARSED → TASK_COMPLETED → ENDPOINT_RELEASED

Scheduler-only phases (this module):
  QUEUED, ASSIGNED, CAPACITY_ACQUIRED, WORKER_INVOKE,
  TASK_COMPLETED | TASK_FAILED | TASK_RETRY | HARD_TIMEOUT,
  CAPACITY_RELEASED, WORKER_STATE_*
"""
from __future__ import annotations

import concurrent.futures
import inspect
import logging
import threading
import time
from dataclasses import dataclass
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


def _task_id(payload: Any) -> str:
    if isinstance(payload, tuple) and payload:
        return f"chunk-{payload[0]}"
    return f"id-{id(payload)}"


def _lifecycle(
    phase: str,
    *,
    task_id: str,
    role: str,
    attempt: int,
    worker: str,
    **extra: Any,
) -> None:
    extras = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
    log.info(
        "TASK_LIFECYCLE phase=%s task=%s role=%s attempt=%s worker=%s%s",
        phase,
        task_id,
        role,
        attempt,
        worker,
        f" {extras}" if extras else "",
    )


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
    orphan_timeouts: int = 0
    pending_after_complete: int = 0
    rate_limit_requeues: int = 0
    rate_limit_backoff_sec_sum: float = 0.0

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
        avg_rl = (
            self.rate_limit_backoff_sec_sum / self.rate_limit_requeues
            if self.rate_limit_requeues
            else 0.0
        )
        return {
            "avg_queue_wait_ms": round(avg_wait, 1),
            "timeouts": self.timeouts,
            "retries": self.retries,
            "empty_retries": self.empty_retries,
            "rate_limit_requeues": self.rate_limit_requeues,
            "avg_rate_limit_backoff_sec": round(avg_rl, 2),
            "soft_ttft_cancels": self.soft_ttft_cancels,
            "chunks_done": self.chunks_done,
            "chunks_per_sec": round(cps, 3),
            "wall_ms": round(self.wall_ms, 1),
            "orphan_timeouts": self.orphan_timeouts,
            "pending_after_complete": self.pending_after_complete,
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


def _supports_deadline(fn: Callable[..., Any]) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    if "deadline_mono" in sig.parameters:
        return True
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False


def _invoke_worker(
    worker_fn: Callable[..., R],
    payload: T,
    deadline_mono: float,
) -> R:
    if _supports_deadline(worker_fn):
        return worker_fn(payload, deadline_mono=deadline_mono)  # type: ignore[call-arg]
    return worker_fn(payload)


def run_capacity_pool(
    items: List[T],
    worker_fn: Callable[..., R],
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
    - Prefer deadline-aware workers (``deadline_mono=``) so NIM leases release
      before the hard wall; non-compliant workers still use a watchdog thread
    - Failed / empty results retry up to ``max_attempts``
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
    # Global concurrency gate (= advertised endpoint capacity). Inner NIM
    # acquire also enforces per-endpoint max_concurrent.
    capacity_sem = threading.Semaphore(capacity)
    deadline_aware = _supports_deadline(worker_fn)

    queue: PriorityWorkQueue[_WorkItem[T]] = PriorityWorkQueue()
    for payload in items:
        tid = _task_id(payload)
        queue.put(
            _WorkItem(payload=payload, enqueued_at=time.perf_counter(), priority=priority),
            priority,
        )
        _lifecycle(
            "QUEUED",
            task_id=tid,
            role=role,
            attempt=1,
            worker="-",
            kind=kind,
        )

    results: Dict[Any, Optional[R]] = {}
    lock = threading.Lock()
    t0 = time.perf_counter()
    last_progress = [0.0]
    # Track in-flight futures that were abandoned (state-machine debt).
    abandoned: List[concurrent.futures.Future] = []

    log.info(
        "Scheduler start role=%s kind=%s items=%s workers=%s capacity=%s "
        "hard_timeout=%.0fs deadline_aware=%s",
        role,
        kind,
        total,
        workers,
        capacity,
        hard_timeout_sec,
        deadline_aware,
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

    def _handle_result(
        item: _WorkItem[T],
        result: Optional[R],
        err: Optional[BaseException],
        *,
        worker: str,
        orphaned: bool = False,
    ) -> None:
        nonlocal progress
        from src.core.nim_rate_limit import (
            compute_backoff_sec,
            is_rate_limit_error,
            record_rate_limit_requeue,
        )

        tid = _task_id(item.payload)
        key = _key(item.payload)
        try:
            ok = err is None and result is not None and is_success(result)
        except Exception as e:
            ok = False
            err = e
            log.exception(
                "TASK_LIFECYCLE phase=IS_SUCCESS_RAISED task=%s err=%s", tid, e
            )

        rate_limited = (not ok) and is_rate_limit_error(err)
        # Rate-limit gets its own requeue budget (capped); genuine hangs/empties
        # use max_attempts as before.
        rl_ceiling = max(
            max_attempts,
            int(getattr(settings, "NIM_RATE_LIMIT_MAX_REQUEUES", 8) or 8),
        )
        attempt_budget = rl_ceiling if rate_limited else max_attempts

        # Deadline-exhausted failures must not spin retries (was burning the
        # rest of the job wall with instant fail→retry loops).
        err_l = str(err or "").lower()
        result_err = ""
        if result is not None:
            try:
                if isinstance(result, tuple) and len(result) >= 2:
                    r1 = result[1]
                    result_err = str(
                        getattr(r1, "summary", "") or getattr(r1, "error", "") or ""
                    )
                else:
                    result_err = str(getattr(result, "summary", "") or "")
            except Exception:
                result_err = ""
        combined = f"{err_l} {result_err}".lower()
        deadline_dead = "deadline" in combined

        with lock:
            progress.running = max(0, progress.running - 1)
            if ok:
                results[key] = result
                progress.completed += 1
                metrics.chunks_done += 1
                phase = "TASK_COMPLETED"
            elif rate_limited and item.attempt + 1 < attempt_budget:
                # Backoff OUTSIDE the lock so other workers keep pulling.
                phase = "RATE_LIMIT_BACKOFF"
            elif (not deadline_dead) and item.attempt + 1 < max_attempts:
                progress.retrying += 1
                metrics.retries += 1
                if err is None:
                    metrics.empty_retries += 1
                nxt = _WorkItem(
                    payload=item.payload,
                    enqueued_at=time.perf_counter(),
                    attempt=item.attempt + 1,
                    priority=item.priority,
                )
                progress.queued += 1
                queue.put(nxt, item.priority)
                phase = "TASK_RETRY"
                _lifecycle(
                    "QUEUED",
                    task_id=tid,
                    role=role,
                    attempt=item.attempt + 2,
                    worker=worker,
                    reason="retry",
                )
            else:
                results[key] = result
                progress.failed += 1
                if err is not None and not rate_limited:
                    metrics.timeouts += 1
                phase = "TASK_FAILED"
            if orphaned:
                metrics.orphan_timeouts += 1

        if phase == "RATE_LIMIT_BACKOFF":
            retry_after = getattr(err, "retry_after_sec", None) if err else None
            backoff = compute_backoff_sec(item.attempt, retry_after_sec=retry_after)
            record_rate_limit_requeue(backoff)
            with lock:
                metrics.rate_limit_requeues += 1
                metrics.rate_limit_backoff_sec_sum += backoff
                metrics.retries += 1
                progress.retrying += 1
            log.info(
                "TASK_LIFECYCLE phase=RATE_LIMIT_BACKOFF task=%s attempt=%s "
                "backoff_sec=%.2f worker=%s",
                tid,
                item.attempt + 1,
                backoff,
                worker,
            )
            time.sleep(backoff)
            with lock:
                progress.queued += 1
                nxt = _WorkItem(
                    payload=item.payload,
                    enqueued_at=time.perf_counter(),
                    attempt=item.attempt + 1,
                    priority=item.priority,
                )
                queue.put(nxt, item.priority)
            _lifecycle(
                "QUEUED",
                task_id=tid,
                role=role,
                attempt=item.attempt + 2,
                worker=worker,
                reason="rate_limit_requeue",
                backoff_sec=round(backoff, 2),
            )
            phase = "TASK_RETRY"

        err_name = type(err).__name__ if err else None
        _lifecycle(
            phase,
            task_id=tid,
            role=role,
            attempt=item.attempt + 1,
            worker=worker,
            ok=ok,
            err=err_name,
            orphaned=orphaned,
            rate_limited=rate_limited,
            completed=progress.completed,
            failed=progress.failed,
            running=progress.running,
            queued=progress.queued,
        )
        if phase == "TASK_RETRY":
            # Keep retrying visible briefly for the dashboard, then clear.
            def _clear_retry() -> None:
                time.sleep(1.5)
                with lock:
                    progress.retrying = max(0, progress.retrying - 1)
                _emit(force=True)

            threading.Thread(
                target=_clear_retry, name=f"retry-vis-{tid}", daemon=True
            ).start()
        _emit(force=True)

    stop = threading.Event()

    def _worker() -> None:
        wname = threading.current_thread().name
        _lifecycle(
            "WORKER_STATE_IDLE",
            task_id="-",
            role=role,
            attempt=0,
            worker=wname,
        )
        while not stop.is_set():
            _lifecycle(
                "WORKER_STATE_PULL",
                task_id="-",
                role=role,
                attempt=0,
                worker=wname,
            )
            item = queue.get(timeout=0.4)
            if item is None:
                with lock:
                    if progress.queued <= 0 and progress.running <= 0:
                        _lifecycle(
                            "WORKER_STATE_EXIT",
                            task_id="-",
                            role=role,
                            attempt=0,
                            worker=wname,
                            reason="drained",
                        )
                        return
                continue

            tid = _task_id(item.payload)
            with lock:
                progress.queued = max(0, progress.queued - 1)
                progress.running += 1
            wait_ms = (time.perf_counter() - item.enqueued_at) * 1000.0
            with lock:
                metrics.record_wait(wait_ms)
            _lifecycle(
                "ASSIGNED",
                task_id=tid,
                role=role,
                attempt=item.attempt + 1,
                worker=wname,
                queue_wait_ms=round(wait_ms, 1),
                running=progress.running,
                queued=progress.queued,
            )
            _emit()

            result: Optional[R] = None
            err: Optional[BaseException] = None
            orphaned = False
            deadline_mono = time.monotonic() + hard_timeout_sec

            _lifecycle(
                "CAPACITY_WAIT",
                task_id=tid,
                role=role,
                attempt=item.attempt + 1,
                worker=wname,
                sem_timeout_s=hard_timeout_sec,
            )
            acquired = capacity_sem.acquire(timeout=hard_timeout_sec)
            if not acquired:
                _lifecycle(
                    "CAPACITY_WAIT_TIMEOUT",
                    task_id=tid,
                    role=role,
                    attempt=item.attempt + 1,
                    worker=wname,
                )
                # Re-queue but consume an attempt so we cannot loop forever
                # while capacity is wedged by orphaned leases.
                with lock:
                    progress.running = max(0, progress.running - 1)
                    metrics.retries += 1
                if item.attempt + 1 < max_attempts:
                    with lock:
                        progress.queued += 1
                        progress.retrying += 1
                    queue.put(
                        _WorkItem(
                            payload=item.payload,
                            enqueued_at=time.perf_counter(),
                            attempt=item.attempt + 1,
                            priority=item.priority,
                        ),
                        item.priority,
                    )
                    _lifecycle(
                        "TASK_RETRY",
                        task_id=tid,
                        role=role,
                        attempt=item.attempt + 1,
                        worker=wname,
                        reason="capacity_sem_timeout",
                    )
                    def _clear() -> None:
                        time.sleep(1.5)
                        with lock:
                            progress.retrying = max(0, progress.retrying - 1)

                    threading.Thread(target=_clear, daemon=True).start()
                else:
                    with lock:
                        results[_key(item.payload)] = None
                        progress.failed += 1
                        metrics.timeouts += 1
                    _lifecycle(
                        "TASK_FAILED",
                        task_id=tid,
                        role=role,
                        attempt=item.attempt + 1,
                        worker=wname,
                        reason="capacity_sem_timeout",
                    )
                _emit(force=True)
                continue

            _lifecycle(
                "CAPACITY_ACQUIRED",
                task_id=tid,
                role=role,
                attempt=item.attempt + 1,
                worker=wname,
                deadline_aware=deadline_aware,
            )
            try:
                _lifecycle(
                    "WORKER_INVOKE",
                    task_id=tid,
                    role=role,
                    attempt=item.attempt + 1,
                    worker=wname,
                    hard_timeout_s=hard_timeout_sec,
                )
                if deadline_aware:
                    # Deadline-aware path: NIM should exit and release leases
                    # before the hard wall. Keep a small grace watchdog so a
                    # stuck socket cannot freeze the worker forever.
                    one = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    fut = one.submit(
                        _invoke_worker, worker_fn, item.payload, deadline_mono
                    )
                    grace = hard_timeout_sec + 2.0
                    try:
                        result = fut.result(timeout=grace)
                    except Exception as e:
                        # builtins.TimeoutError is an alias of
                        # concurrent.futures.TimeoutError — only treat as an
                        # orphaning hard-timeout when the future is still running.
                        if isinstance(e, TimeoutError) and not fut.done():
                            err = e
                            orphaned = True
                            abandoned.append(fut)
                            with lock:
                                metrics.timeouts += 1
                            _lifecycle(
                                "HARD_TIMEOUT",
                                task_id=tid,
                                role=role,
                                attempt=item.attempt + 1,
                                worker=wname,
                                orphan_risk=True,
                                note="deadline_aware_worker_exceeded_grace",
                            )
                            log.warning(
                                "Scheduler grace hard-timeout after %.0fs role=%s "
                                "attempt=%s task=%s (deadline path stuck; lease may orphan)",
                                grace,
                                role,
                                item.attempt + 1,
                                tid,
                            )
                        else:
                            err = e
                    finally:
                        try:
                            one.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            one.shutdown(wait=False)
                else:
                    # Legacy / test workers: watchdog hard wall. Abandoning the
                    # future can orphan endpoint leases — logged explicitly.
                    one = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    fut = one.submit(
                        _invoke_worker, worker_fn, item.payload, deadline_mono
                    )
                    try:
                        result = fut.result(timeout=hard_timeout_sec)
                    except Exception as e:
                        if isinstance(e, TimeoutError) and not fut.done():
                            err = e
                            orphaned = True
                            abandoned.append(fut)
                            with lock:
                                metrics.timeouts += 1
                            _lifecycle(
                                "HARD_TIMEOUT",
                                task_id=tid,
                                role=role,
                                attempt=item.attempt + 1,
                                worker=wname,
                                orphan_risk=True,
                                note="worker_ignored_deadline_lease_may_linger",
                            )
                            log.warning(
                                "Scheduler hard-timeout after %.0fs role=%s attempt=%s "
                                "task=%s (non-deadline worker; endpoint lease may orphan)",
                                hard_timeout_sec,
                                role,
                                item.attempt + 1,
                                tid,
                            )
                        else:
                            err = e
                    finally:
                        try:
                            one.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            one.shutdown(wait=False)
            finally:
                capacity_sem.release()
                _lifecycle(
                    "CAPACITY_RELEASED",
                    task_id=tid,
                    role=role,
                    attempt=item.attempt + 1,
                    worker=wname,
                )

            if err is not None and isinstance(err, concurrent.futures.TimeoutError):
                pass  # already logged
            elif err is not None and "deadline" in str(err).lower():
                with lock:
                    metrics.timeouts += 1
                _lifecycle(
                    "HARD_TIMEOUT",
                    task_id=tid,
                    role=role,
                    attempt=item.attempt + 1,
                    worker=wname,
                    orphan_risk=False,
                    err=type(err).__name__,
                )
                log.warning(
                    "Scheduler deadline exceeded after %.0fs role=%s attempt=%s task=%s",
                    hard_timeout_sec,
                    role,
                    item.attempt + 1,
                    tid,
                )

            _handle_result(item, result, err, worker=wname, orphaned=orphaned)
            _lifecycle(
                "WORKER_STATE_IDLE",
                task_id=tid,
                role=role,
                attempt=item.attempt + 1,
                worker=wname,
            )

    threads = [
        threading.Thread(target=_worker, name=f"sched-{role}-{i}", daemon=True)
        for i in range(workers)
    ]
    for th in threads:
        th.start()
        _lifecycle(
            "WORKER_STATE_STARTED",
            task_id="-",
            role=role,
            attempt=0,
            worker=th.name,
        )

    while True:
        with lock:
            done = progress.completed + progress.failed
            if done >= total and progress.queued <= 0 and progress.running <= 0:
                break
        _emit()
        time.sleep(0.25)
        if (time.perf_counter() - t0) > hard_timeout_sec * max(2, total) + 60:
            log.error("Scheduler safety wall hit role=%s total=%s", role, total)
            break

    stop.set()
    queue.close()
    for th in threads:
        th.join(timeout=2.0)

    # Detect futures still pending after the wave should be done.
    still_pending = sum(1 for f in abandoned if not f.done())
    metrics.pending_after_complete = still_pending
    if still_pending:
        log.error(
            "TASK_LIFECYCLE phase=PENDING_FUTURES_AFTER_WAVE role=%s pending=%s "
            "abandoned=%s — endpoint leases may still be held by zombie HTTP threads",
            role,
            still_pending,
            len(abandoned),
        )

    metrics.wall_ms = (time.perf_counter() - t0) * 1000.0
    _emit(force=True)
    log.info(
        "Scheduler done role=%s completed=%s failed=%s timeouts=%s orphan_timeouts=%s "
        "pending_futures=%s wall_ms=%.0f",
        role,
        progress.completed,
        progress.failed,
        metrics.timeouts,
        metrics.orphan_timeouts,
        still_pending,
        metrics.wall_ms,
    )

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
