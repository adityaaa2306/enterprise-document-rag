"""Regression: never downgrade durable complete with stale in-memory pending."""
from __future__ import annotations

from src.core import job_status as job_status_mod
from src.db import jobs as job_store


def test_get_job_does_not_downgrade_complete_with_stale_pending(monkeypatch):
    job_id = "deadbeef-0000-0000-0000-000000000001"
    job_store.JOB_STATUSES[job_id] = {
        "job_id": job_id,
        "status": job_status_mod.STATUS_PENDING,
        "progress": 100.0,
        "message": "Summary Ready · Search available",
        "result": {"final_summary": "Hello", "summary_ready": True},
    }

    class _Row:
        id = job_id
        user_id = None
        owner_type = "guest"
        owner_id = "guest-1"
        status = "complete"
        progress = 100.0
        message = "Search Ready"
        filename = "doc.pdf"
        job_mode = None
        claimed_by = None
        claimed_at = None
        attempt_count = 1
        error_detail = None
        available_at = None
        heartbeat_at = None
        created_at = None
        updated_at = None
        completed_at = None
        result_json = {
            "final_summary": "Hello from DB",
            "summary_ready": True,
            "document_id": job_id,
        }
        understanding = None
        confidence = None
        latency_ms = None
        carbon_saved_grams = None
        routing_decision = None
        selected_model = None
        crs = None

    class _DB:
        def get(self, *_a, **_k):
            return _Row()

        def close(self):
            return None

    monkeypatch.setattr(job_store, "_db_enabled", lambda: True)
    monkeypatch.setattr("src.db.session.get_session", lambda: _DB())

    status = job_store.get_job(job_id, include_result=True)
    assert status is not None
    assert job_status_mod.normalize_job_status(status.get("status")) == "complete"
    assert (status.get("result") or {}).get("final_summary")
    assert job_status_mod.is_job_ready_for_result(status) is True

    light = job_store.get_job(job_id, include_result=False)
    assert light is not None
    assert job_status_mod.normalize_job_status(light.get("status")) == "complete"
