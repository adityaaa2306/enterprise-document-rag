"""
Durable document-processing worker (Phase 3).

Polls the jobs table, claims pending rows atomically, invokes the existing
agentic pipeline unchanged, and persists progress / results.
"""
from src.worker.loop import run_worker_forever
from src.worker.runner import process_claimed_job

__all__ = ["run_worker_forever", "process_claimed_job"]
