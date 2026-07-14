"""Worker poll loop: heartbeat, reclaim stale claims, claim + process.

Graceful shutdown (Phase 4): SIGTERM/SIGINT stop new claims after the
current job finishes (or immediately if idle). Stale reclaim recovers
jobs if the process is killed mid-flight.
"""
from __future__ import annotations

import logging
import signal
import socket
import threading
import time
import uuid
from typing import Optional

from src.core.config import settings
from src.db import jobs as job_store
from src.worker.runner import process_claimed_job

log = logging.getLogger("worker.loop")

# Process-wide stop flag (set by signal handlers)
_shutdown = threading.Event()
_busy = threading.Event()


def request_shutdown(reason: str = "signal") -> None:
    """Idempotent: stop claiming new work after the current job."""
    if not _shutdown.is_set():
        log.info("Worker shutdown requested (%s) — will not claim new jobs", reason)
    _shutdown.set()


def is_shutdown_requested() -> bool:
    return _shutdown.is_set()


def resolve_worker_id(explicit: Optional[str] = None) -> str:
    configured = (explicit or settings.WORKER_ID or "").strip()
    if configured:
        return configured
    return f"{socket.gethostname()}-{os_getpid()}-{uuid.uuid4().hex[:8]}"


def os_getpid() -> int:
    import os

    return os.getpid()


def _install_signal_handlers() -> None:
    def _handler(signum, frame):  # noqa: ARG001
        try:
            name = signal.Signals(signum).name
        except Exception:
            name = str(signum)
        request_shutdown(name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except Exception as e:
            log.warning("Could not install handler for %s: %s", sig, e)


def run_worker_forever(
    *,
    worker_id: Optional[str] = None,
    once: bool = False,
    embedded: bool = False,
) -> None:
    """
    Main worker lifecycle.

    once=True processes at most one claim cycle (for tests).
    embedded=True: run inside the API process (daemon thread). Skips duplicate
    signal handlers / model+DB init so free-tier memory stays single-process.
    SIGTERM/SIGINT (standalone): finish current job (if any), then exit cleanly.
    """
    _shutdown.clear()
    _busy.clear()
    if not embedded:
        _install_signal_handlers()

    wid = resolve_worker_id(worker_id)
    poll = float(settings.WORKER_POLL_INTERVAL_SEC)
    hb_every = float(settings.WORKER_HEARTBEAT_INTERVAL_SEC)
    reclaim_every = float(settings.WORKER_RECLAIM_INTERVAL_SEC)
    grace = float(getattr(settings, "WORKER_SHUTDOWN_GRACE_SEC", 120) or 120)

    log.info(
        "Worker starting id=%s mode=%s poll=%.1fs claim_timeout=%ss max_attempts=%s grace=%.0fs",
        wid,
        "embedded-thread" if embedded else "standalone",
        poll,
        settings.WORKER_CLAIM_TIMEOUT_SEC,
        settings.WORKER_MAX_ATTEMPTS,
        grace,
    )

    if not embedded:
        from src.memory import storage

        log.info("Worker: ensuring database + Chroma are ready...")
        storage.init_database()  # DB + embedded Chroma PersistentClient
        from src.agents import models as agent_models

        agent_models.load_all_models()
    else:
        log.info("Worker: embedded mode — reusing API process DB/Chroma/NIM clients")

    # Restart recovery: same WORKER_ID often keeps a dead "processing" claim that
    # blocks the queue until WORKER_CLAIM_TIMEOUT_SEC (e.g. mid-compile kill).
    released = job_store.release_orphaned_claims_for_worker(wid)
    if released:
        log.warning(
            "Worker %s: released %s orphaned processing claim(s) from prior process",
            wid,
            released,
        )

    job_store.upsert_worker_heartbeat(wid, status="idle", hostname=socket.gethostname(), meta={})
    last_hb = 0.0
    last_reclaim = 0.0
    shutdown_deadline: Optional[float] = None

    try:
        while True:
            if _shutdown.is_set():
                if shutdown_deadline is None:
                    shutdown_deadline = time.monotonic() + grace
                    log.info(
                        "Draining worker %s (grace=%.0fs, busy=%s)",
                        wid,
                        grace,
                        _busy.is_set(),
                    )
                if not _busy.is_set():
                    log.info("Worker %s idle — exiting after shutdown request", wid)
                    break
                if time.monotonic() >= shutdown_deadline:
                    log.warning(
                        "Worker %s grace period elapsed while busy — exiting; "
                        "in-flight job will be reclaimed if not completed",
                        wid,
                    )
                    break
                # Still busy: wait briefly without claiming
                time.sleep(min(0.5, poll))
                continue

            now = time.monotonic()
            if now - last_hb >= hb_every:
                job_store.upsert_worker_heartbeat(wid, status="idle")
                last_hb = now

            if now - last_reclaim >= reclaim_every:
                job_store.reclaim_stale_jobs()
                last_reclaim = now

            claimed = job_store.claim_next_job(wid)
            if claimed:
                if _shutdown.is_set():
                    # Extremely narrow race: release back to pending
                    from src.core import job_status as job_status_mod

                    jid = claimed["job_id"]
                    log.info("Shutdown in progress — releasing freshly claimed job %s", jid)
                    job_store.upsert_job(
                        jid,
                        status=job_status_mod.STATUS_PENDING,
                        claimed_by=None,
                        claimed_at=None,
                        heartbeat_at=None,
                        message="Released on worker shutdown",
                        available_at=job_store._now(),
                        progress=0.0,
                    )
                    break

                jid = claimed["job_id"]
                log.info("Claimed job %s (attempt=%s)", jid, claimed.get("attempt_count"))
                job_store.upsert_worker_heartbeat(
                    wid, status="busy", meta={"current_job_id": jid}
                )
                _busy.set()
                try:
                    process_claimed_job(claimed, worker_id=wid)
                except Exception as e:
                    log.exception("Job %s failed in worker: %s", jid, e)
                finally:
                    _busy.clear()
                    job_store.upsert_worker_heartbeat(wid, status="idle", meta={})
                    last_hb = time.monotonic()
                if once or _shutdown.is_set():
                    return
                continue

            if once:
                return
            # Interruptible sleep
            _shutdown.wait(timeout=poll)
    except KeyboardInterrupt:
        request_shutdown("KeyboardInterrupt")
        log.info("Worker %s shutting down (KeyboardInterrupt)", wid)
    finally:
        try:
            job_store.upsert_worker_heartbeat(wid, status="stopped")
        except Exception:
            pass
        log.info("Worker %s stopped", wid)
