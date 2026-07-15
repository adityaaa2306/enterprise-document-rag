"""Lifecycle sync helpers — Summary Ready vs metrics ready."""
from src.core.sync_lifecycle import metrics_ready_from_status, summary_ready_from_status


def test_summary_ready_before_metrics():
    early = {
        "status": "complete",
        "progress": 91.0,
        "message": "Summary Ready",
        "partial": {"summary_ready": True},
        "background": {"phase": "carbon", "message": "Updating carbon metrics…"},
        "result": {
            "summary_ready": True,
            "final_summary": "Hello",
            "carbon_data": {"actual_cost_gco2e": 0.0, "total_chunks": 0},
        },
    }
    assert summary_ready_from_status(early) is True
    assert metrics_ready_from_status(early) is False


def test_metrics_ready_on_search_ready():
    done = {
        "status": "complete",
        "progress": 100.0,
        "message": "Search Ready",
        "background": {"phase": "search_ready", "message": "Search Ready"},
        "result": {
            "summary_ready": True,
            "final_summary": "Hello",
            "carbon_data": {
                "total_chunks": 30,
                "baseline_cost_gco2e": 100.0,
                "region_decision": {"selected_region_name": "India"},
            },
            "background": {"phase": "search_ready"},
        },
    }
    assert summary_ready_from_status(done) is True
    assert metrics_ready_from_status(done) is True
