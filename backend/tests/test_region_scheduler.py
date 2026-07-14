"""Tests for Carbon-Aware Region Scheduler (single-region production shape)."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from src.carbon.scheduler import (
    MODE_CARBON_OPTIMIZED,
    MODE_SINGLE_REGION,
    ElectricityMapsProvider,
    ExecutionRegion,
    RegionDecision,
    RegionRegistry,
    RegionScheduler,
    RegionStatus,
    WorkloadEstimate,
    estimate_workload_from_state,
    reset_region_registry_for_tests,
    reset_region_scheduler_for_tests,
    schedule_region,
)
from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.providers.carbon_provider import CarbonProvider


class _FixedProvider(CarbonProvider):
    provider_id = "fixed_test"

    def __init__(self, intensity: float = 412.0, zone: str = "IN-WE") -> None:
        self.intensity = intensity
        self.zone = zone

    def get_grid_intensity(self, region: ExecutionRegion) -> GridCarbonData:
        return GridCarbonData(
            intensity_gco2_kwh=self.intensity,
            zone=self.zone,
            provider=self.provider_id,
            source="test_provider",
            data_freshness="live",
            confidence="high",
        )


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_region_registry_for_tests()
    reset_region_scheduler_for_tests()
    yield
    reset_region_registry_for_tests()
    reset_region_scheduler_for_tests()


def test_registry_has_single_active_india(monkeypatch):
    monkeypatch.setattr("src.carbon.scheduler.registry.settings.REGION_SCHEDULER_DEFAULT_REGION", "india")
    monkeypatch.setattr("src.carbon.scheduler.registry.settings.REGION_SCHEDULER_DEFAULT_REGION_NAME", "India")
    reset_region_registry_for_tests()
    from src.carbon.scheduler.registry import get_region_registry

    reg = get_region_registry()
    active = reg.active_executable()
    assert len(active) == 1
    assert active[0].id == "india"
    assert active[0].display_name == "India"
    assert active[0].status == RegionStatus.ACTIVE
    assert active[0].supports_execution is True


def test_single_region_schedule_does_not_pretend_global():
    reg = RegionRegistry(
        [
            ExecutionRegion(
                id="india",
                display_name="India",
                provider="electricity_maps",
                grid_zone="",
                status=RegionStatus.ACTIVE,
                supports_execution=True,
                latitude=18.52,
                longitude=73.85,
            )
        ]
    )
    sched = RegionScheduler(
        registry=reg,
        provider=_FixedProvider(455.0, "IN-WE"),
        mode=MODE_SINGLE_REGION,
    )
    decision = sched.schedule(WorkloadEstimate(job_id="j1", estimated_tokens=1000))
    assert isinstance(decision, RegionDecision)
    assert decision.selected_region.id == "india"
    assert decision.scheduling_mode == MODE_SINGLE_REGION
    assert decision.execution_status == "configured_region"
    assert decision.grid.intensity_gco2_kwh == 455.0
    assert "configured execution region" in decision.reason.lower()
    assert "multi-region" in decision.future_support or "multi_region" in decision.future_support
    d = decision.to_dict()
    assert d["data_source"] == "live"
    assert d["provider"] == "fixed_test"


def test_carbon_optimized_with_one_region_falls_back_honestly():
    reg = RegionRegistry(
        [
            ExecutionRegion(
                id="india",
                display_name="India",
                provider="electricity_maps",
                grid_zone="IN-WE",
                status=RegionStatus.ACTIVE,
                supports_execution=True,
            )
        ]
    )
    sched = RegionScheduler(
        registry=reg,
        provider=_FixedProvider(),
        mode=MODE_CARBON_OPTIMIZED,
    )
    decision = sched.schedule()
    assert decision.selected_region.id == "india"
    assert "only one" in decision.reason.lower() or "falling back" in decision.reason.lower()
    assert decision.meta.get("carbon_optimized_fallback") is True


def test_carbon_optimized_picks_lowest_among_multiple():
    reg = RegionRegistry(
        [
            ExecutionRegion(
                id="india",
                display_name="India",
                provider="test",
                grid_zone="IN",
                status=RegionStatus.ACTIVE,
                supports_execution=True,
            ),
            ExecutionRegion(
                id="finland",
                display_name="Finland",
                provider="test",
                grid_zone="FI",
                status=RegionStatus.ACTIVE,
                supports_execution=True,
            ),
        ]
    )

    class _ByRegion(_FixedProvider):
        def get_grid_intensity(self, region: ExecutionRegion) -> GridCarbonData:
            intensity = 100.0 if region.id == "finland" else 500.0
            return GridCarbonData(
                intensity_gco2_kwh=intensity,
                zone=region.grid_zone,
                provider=self.provider_id,
                source="test",
                data_freshness="live",
                confidence="high",
            )

    sched = RegionScheduler(
        registry=reg, provider=_ByRegion(), mode=MODE_CARBON_OPTIMIZED
    )
    decision = sched.schedule()
    assert decision.selected_region.id == "finland"
    assert decision.grid.intensity_gco2_kwh == 100.0
    assert decision.scheduling_mode == MODE_CARBON_OPTIMIZED


def test_accounting_uses_region_scheduler_not_direct_em(monkeypatch):
    """estimate_workflow_carbon without grid= must go through schedule_region."""
    from src.carbon.accounting import estimate_workflow_carbon

    called = {"n": 0}

    def _fake_schedule(workload=None):
        called["n"] += 1
        region = ExecutionRegion(
            id="india",
            display_name="India",
            provider="electricity_maps",
            grid_zone="IN-WE",
            status=RegionStatus.ACTIVE,
            supports_execution=True,
        )
        grid = GridCarbonData(
            intensity_gco2_kwh=333.0,
            zone="IN-WE",
            provider="electricity_maps",
            source="electricity_maps",
            data_freshness="live",
            confidence="high",
        )
        return RegionDecision(
            selected_region=region,
            reason="test",
            grid=grid,
            provider="electricity_maps",
            scheduling_mode=MODE_SINGLE_REGION,
            timestamp=RegionDecision.now_iso(),
            data_freshness="live",
            confidence="high",
        )

    monkeypatch.setattr(
        "src.carbon.scheduler.region_scheduler.schedule_region", _fake_schedule
    )
    # accounting imports schedule_region inside the function from package
    monkeypatch.setattr("src.carbon.scheduler.schedule_region", _fake_schedule)

    state: Dict[str, Any] = {
        "job_id": "sched-acct",
        "chunks": [type("C", (), {"content": "hello world " * 50})()],
        "summaries": ["summary text"],
        "final_summary": "final",
        "total_chunks": 1,
        "chunks_escalated": 0,
        "routing_decision": {"tier": "medium", "compile_tier": "heavy"},
        "model_usage_chars": {"light": 0, "medium": 100, "large": 0},
    }
    report = estimate_workflow_carbon("sched-acct", state)
    assert called["n"] >= 1
    assert report["local_grid_gco2_kwh"] == 333.0
    assert report["region_decision"] is not None
    assert report["region_decision"]["selected_region_id"] == "india"
    assert report["region_decision"]["scheduling_mode"] == MODE_SINGLE_REGION


def test_workload_estimate_from_state():
    class C:
        content = "abcd" * 25

    wl = estimate_workload_from_state(
        {"job_id": "w1", "chunks": [C()], "total_chunks": 1, "summaries": []}
    )
    assert wl.job_id == "w1"
    assert wl.estimated_chunks == 1
    assert wl.document_chars == 100
    assert wl.estimated_tokens == 25


def test_electricity_maps_provider_wraps_client(monkeypatch):
    captured = {}

    def _fake_fetch(**kwargs):
        captured.update(kwargs)
        return {
            "intensity_gco2_kwh": 501.0,
            "zone": "IN-WE",
            "source": "electricity_maps",
            "datetime": "2026-07-14T00:00:00Z",
            "updated_at": None,
            "is_estimated": False,
            "cache_hit": False,
            "error": None,
        }

    monkeypatch.setattr(
        "src.carbon.scheduler.providers.electricity_maps_provider.fetch_grid_carbon_intensity",
        _fake_fetch,
    )
    provider = ElectricityMapsProvider()
    region = ExecutionRegion(
        id="india",
        display_name="India",
        provider="electricity_maps",
        grid_zone="",
        latitude=18.52,
        longitude=73.85,
    )
    data = provider.get_grid_intensity(region)
    assert data.intensity_gco2_kwh == 501.0
    assert data.data_freshness == "live"
    assert data.confidence == "high"
    assert captured.get("lat") == 18.52
