"""
Repair queue — quality repairs WITHOUT mutating the frozen DAG topology.

Repair tasks re-run existing node ids; they never insert nodes or rewrite deps.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class RepairTask:
    node_id: str
    reason: str
    priority: int = 50
    attempts: int = 0
    max_attempts: int = 2
    enqueued_at: float = field(default_factory=time.time)
    completed: bool = False
    success: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RepairQueue:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._lock = threading.Lock()
        self._tasks: List[RepairTask] = []
        self._done: List[RepairTask] = []

    def enqueue(self, node_id: str, reason: str, *, priority: int = 50) -> None:
        with self._lock:
            # Dedup pending by node_id
            for t in self._tasks:
                if t.node_id == node_id and not t.completed:
                    t.reason = reason
                    t.priority = min(t.priority, priority)
                    return
            self._tasks.append(RepairTask(node_id=node_id, reason=reason, priority=priority))
            self._tasks.sort(key=lambda x: x.priority)

    def pending(self) -> List[RepairTask]:
        with self._lock:
            return [t for t in self._tasks if not t.completed]

    def pop_batch(self, n: int = 3) -> List[RepairTask]:
        with self._lock:
            out: List[RepairTask] = []
            for t in self._tasks:
                if not t.completed and len(out) < n:
                    out.append(t)
            return out

    def mark_done(self, task: RepairTask, *, success: bool, error: Optional[str] = None) -> None:
        with self._lock:
            task.completed = True
            task.success = success
            task.error = error
            task.attempts += 1
            self._done.append(task)

    def report(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pending": [t.to_dict() for t in self._tasks if not t.completed],
                "done": [t.to_dict() for t in self._done[-20:]],
                "enqueued": len(self._tasks),
                "completed": sum(1 for t in self._done if t.success),
                "failed": sum(1 for t in self._done if t.completed and not t.success),
            }


def run_repair_tasks(
    queue: RepairQueue,
    *,
    recompute_fn: Callable[[str], bool],
    max_tasks: int = 3,
) -> Dict[str, Any]:
    """
    Execute up to max_tasks repairs. ``recompute_fn(node_id)`` must NOT mutate topology.
    """
    batch = queue.pop_batch(max_tasks)
    for task in batch:
        try:
            ok = bool(recompute_fn(task.node_id))
            queue.mark_done(task, success=ok)
        except Exception as e:
            log.warning("Repair task %s failed: %s", task.node_id, e)
            queue.mark_done(task, success=False, error=str(e))
    return queue.report()
