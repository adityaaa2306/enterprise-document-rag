"""In-process embedded worker (Render free-tier)."""
from __future__ import annotations

import threading
import time


def test_run_worker_forever_embedded_skips_reinit(monkeypatch):
    from src.worker import loop as worker_loop

    calls = {"init": 0, "models": 0}

    def fake_init(*_a, **_k):
        calls["init"] += 1

    def fake_models():
        calls["models"] += 1

    monkeypatch.setattr(worker_loop, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "src.memory.storage.init_database",
        fake_init,
        raising=False,
    )

    # Force once=True path quickly: claim nothing
    monkeypatch.setattr(worker_loop.job_store, "upsert_worker_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(worker_loop.job_store, "reclaim_stale_jobs", lambda: 0)
    monkeypatch.setattr(worker_loop.job_store, "claim_next_job", lambda *_a, **_k: None)

    # Stop quickly after one poll
    def stop_soon():
        time.sleep(0.05)
        worker_loop.request_shutdown("test")

    threading.Thread(target=stop_soon, daemon=True).start()
    worker_loop.run_worker_forever(worker_id="test-embedded", once=True, embedded=True)
    assert calls["init"] == 0
    assert calls["models"] == 0


def test_api_lifespan_mentions_embedded_thread():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "RUN_EMBEDDED_WORKER" in text
    assert '"embedded": True' in text or "embedded=True" in text
    assert "embedded-durable-worker" in text
