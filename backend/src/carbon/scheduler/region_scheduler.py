"""
Carbon-Aware Region Scheduler.

Independent of model routing (light/medium/heavy). Selects an execution region,
obtains grid intensity via CarbonProvider, and returns a RegionDecision.

Current production mode: **single-region** (one live Electricity Maps zone).
Future mode: **carbon-optimized** multi-region selection — algorithm stub only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from src.carbon.scheduler.models.decision import RegionDecision, WorkloadEstimate
from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.providers.carbon_provider import CarbonProvider
from src.carbon.scheduler.providers.electricity_maps_provider import ElectricityMapsProvider
from src.carbon.scheduler.registry import RegionRegistry, get_region_registry
from src.core.config import settings

log = logging.getLogger(__name__)

MODE_SINGLE_REGION = "single-region"
MODE_CARBON_OPTIMIZED = "carbon-optimized"


def normalize_scheduling_mode(raw: Optional[str]) -> str:
    mode = str(raw or MODE_SINGLE_REGION).strip().lower().replace("_", "-")
    if mode in {"single", "single-region", "singleregion"}:
        return MODE_SINGLE_REGION
    if mode in {"carbon-optimized", "carbonoptimised", "multi-region", "multiregion"}:
        return MODE_CARBON_OPTIMIZED
    return MODE_SINGLE_REGION


def estimate_workload_from_state(state: Optional[Mapping[str, Any]] = None) -> WorkloadEstimate:
    """
    Workload Estimation step — independent of model scheduler.

    Uses document/chunk signals already present on agent state when available.
    """
    state = state or {}
    chunks = state.get("chunks") or []
    summaries = state.get("summaries") or []
    n_chunks = int(state.get("total_chunks") or len(chunks) or 0)
    chars = 0
    for c in chunks:
        text = getattr(c, "content", None)
        if text is None and isinstance(c, dict):
            text = c.get("content") or c.get("text") or ""
        chars += len(str(text or ""))
    if chars <= 0:
        for s in summaries:
            chars += len(str(s or ""))
    # Rough token estimate (~4 chars/token) for telemetry only
    tokens = max(0, chars // 4)
    return WorkloadEstimate(
        job_id=str(state.get("job_id") or "") or None,
        estimated_tokens=tokens,
        estimated_chunks=n_chunks,
        document_chars=chars,
        meta={"source": "agent_state"},
    )


class RegionScheduler:
    """
    Production-shaped carbon-aware region scheduler.

    schedule(workload) → RegionDecision
    """

    def __init__(
        self,
        *,
        registry: Optional[RegionRegistry] = None,
        provider: Optional[CarbonProvider] = None,
        mode: Optional[str] = None,
    ) -> None:
        self.registry = registry or get_region_registry()
        self.mode = normalize_scheduling_mode(
            mode
            if mode is not None
            else getattr(settings, "REGION_SCHEDULER_MODE", MODE_SINGLE_REGION)
        )
        if provider is not None:
            self.provider = provider
        else:
            provider_id = str(
                getattr(settings, "REGION_SCHEDULER_PROVIDER", "electricity_maps")
                or "electricity_maps"
            ).strip()
            if provider_id != "electricity_maps":
                log.warning(
                    "Unknown REGION_SCHEDULER_PROVIDER=%s — using electricity_maps",
                    provider_id,
                )
            self.provider = ElectricityMapsProvider()

    def schedule(
        self,
        workload: Optional[Union[WorkloadEstimate, Mapping[str, Any]]] = None,
    ) -> RegionDecision:
        wl = self._coerce_workload(workload)

        if self.mode == MODE_CARBON_OPTIMIZED:
            # Future extension: compare intensities across ACTIVE regions and pick
            # the lowest. Not enabled — free-tier has one live zone only.
            decision = self._schedule_carbon_optimized(wl)
        else:
            decision = self._schedule_single_region(wl)

        log.info(
            "RegionScheduler decision: region=%s provider=%s zone=%s "
            "intensity=%.1f mode=%s freshness=%s confidence=%s job=%s",
            decision.selected_region.id,
            decision.provider,
            decision.grid.zone,
            decision.grid.intensity_gco2_kwh,
            decision.scheduling_mode,
            decision.data_freshness,
            decision.confidence,
            (wl.job_id if wl else None),
        )
        return decision

    def _coerce_workload(
        self, workload: Optional[Union[WorkloadEstimate, Mapping[str, Any]]]
    ) -> WorkloadEstimate:
        if workload is None:
            return WorkloadEstimate()
        if isinstance(workload, WorkloadEstimate):
            return workload
        if isinstance(workload, Mapping):
            return estimate_workload_from_state(dict(workload))
        return WorkloadEstimate()

    def _schedule_single_region(self, workload: WorkloadEstimate) -> RegionDecision:
        region = self.registry.default_region()
        grid = self.provider.get_grid_intensity(region)
        reason = (
            "Current implementation uses the configured execution region "
            f"({region.display_name}). Multi-region carbon-optimized scheduling "
            "is not active — Electricity Maps free tier provides live data for "
            "this configured zone only."
        )
        return RegionDecision(
            selected_region=region,
            reason=reason,
            grid=grid,
            provider=self.provider.provider_id,
            scheduling_mode=MODE_SINGLE_REGION,
            timestamp=RegionDecision.now_iso(),
            data_freshness=grid.data_freshness,
            confidence=grid.confidence,
            execution_status="configured_region",
            future_support="multi_region_scheduling",
            workload=workload,
            meta={"enabled_modes": [MODE_SINGLE_REGION], "planned_modes": [MODE_CARBON_OPTIMIZED]},
        )

    def _schedule_carbon_optimized(self, workload: WorkloadEstimate) -> RegionDecision:
        """
        Future path: pick lowest-intensity ACTIVE region.

        Until multiple live regions are licensed, this falls back to single-region
        behaviour with an explicit reason — never fabricates global routing.
        """
        candidates = self.registry.active_executable()
        if len(candidates) <= 1:
            decision = self._schedule_single_region(workload)
            decision.scheduling_mode = MODE_CARBON_OPTIMIZED
            decision.reason = (
                "Carbon-optimized mode requested, but only one ACTIVE executable "
                "region is registered. Falling back to that configured region "
                "(no simulated multi-region routing)."
            )
            decision.meta = {
                **(decision.meta or {}),
                "carbon_optimized_fallback": True,
                "candidate_count": len(candidates),
            }
            return decision

        scored = []
        for region in candidates:
            grid = self.provider.get_grid_intensity(region)
            scored.append((float(grid.intensity_gco2_kwh), region, grid))
        scored.sort(key=lambda t: t[0])
        intensity, region, grid = scored[0]
        return RegionDecision(
            selected_region=region,
            reason=(
                f"Selected lowest live grid intensity among {len(scored)} ACTIVE "
                f"regions ({region.display_name} @ {intensity:.1f} gCO₂e/kWh)."
            ),
            grid=grid,
            provider=self.provider.provider_id,
            scheduling_mode=MODE_CARBON_OPTIMIZED,
            timestamp=RegionDecision.now_iso(),
            data_freshness=grid.data_freshness,
            confidence=grid.confidence,
            execution_status="carbon_optimized_selection",
            future_support="multi_region_scheduling",
            workload=workload,
            meta={
                "candidates": [
                    {
                        "region_id": r.id,
                        "intensity_gco2_kwh": float(g.intensity_gco2_kwh),
                        "zone": g.zone,
                    }
                    for _, r, g in scored
                ]
            },
        )


_SCHEDULER: Optional[RegionScheduler] = None


def get_region_scheduler() -> RegionScheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = RegionScheduler()
    return _SCHEDULER


def reset_region_scheduler_for_tests() -> None:
    global _SCHEDULER
    _SCHEDULER = None


def schedule_region(
    workload: Optional[Union[WorkloadEstimate, Mapping[str, Any]]] = None,
) -> RegionDecision:
    """Module-level convenience: RegionDecision = schedule(workload)."""
    return get_region_scheduler().schedule(workload)
