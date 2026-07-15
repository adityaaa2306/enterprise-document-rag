"""Regression: Summary Ready partial carbon_data must not 500 /job-result."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.schemas import CarbonData, SummaryResponse
from src.db import jobs as job_store


def test_carbon_data_accepts_summary_ready_partial():
    """Fields filled later by background must not be required at Summary Ready."""
    cd = CarbonData.model_validate(
        {
            "total_chunks": 11,
            "modeled_co2e_g": 0.01,
            "operational_co2e_g": 0.01,
            "baseline_cost_gco2e": 0.02,
            "actual_cost_gco2e": 0.01,
            "carbon_saved_grams": 0.01,
            "efficiency_percent": 50.0,
            "primary_metric": "operational_co2e_g",
            "processing_time_seconds": 12.0,
        }
    )
    assert cd.message is None
    assert cd.chunks_escalated is None
    assert cd.local_grid_gco2_kwh is None
    assert cd.compute_location is None


def test_job_result_e3487747_no_500_on_partial_carbon(monkeypatch):
    jid = "e3487747-4a89-4faf-9408-b7312b09b18f"
    gid = "d0abc207-a4d4-45bb-a1be-2f73c3acacea"
    partial = {
        "job_id": jid,
        "status": "complete",
        "progress": 100.0,
        "message": "Summary Ready · Finishing analytics…",
        "owner_type": "guest",
        "owner_id": gid,
        "result": {
            "job_id": jid,
            "document_id": jid,
            "filename": "Student Attendance App.pdf",
            "final_summary": "# Summary\n\nHello",
            "summary_ready": True,
            "background": {"phase": "queued", "message": "Background Indexing"},
            "carbon_data": {
                "total_chunks": 11,
                "modeled_co2e_g": 0.01,
                "operational_co2e_g": 0.01,
                "baseline_cost_gco2e": 0.02,
                "actual_cost_gco2e": 0.01,
                "carbon_saved_grams": 0.01,
                "efficiency_percent": 50.0,
                "primary_metric": "operational_co2e_g",
                "processing_time_seconds": 12.0,
                # intentionally omit message, chunks_escalated, local_grid_gco2_kwh, compute_location
            },
        },
    }

    monkeypatch.setattr(job_store, "get_job", lambda *a, **k: dict(partial))
    monkeypatch.setattr(job_store, "upsert_job", lambda *a, **k: dict(partial))

    from src.db import guests as guest_store

    monkeypatch.setattr(
        guest_store,
        "touch_guest_session",
        lambda sid: {
            "session_id": sid,
            "status": "active",
            "anonymous_name": "Guest-Test",
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    )

    client = TestClient(app)
    res = client.get(f"/job-result/{jid}", headers={"X-Guest-Session-Id": gid})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["final_summary"]
    assert "carbon_data" in body
    # Round-trip through schema
    SummaryResponse.model_validate(body)
