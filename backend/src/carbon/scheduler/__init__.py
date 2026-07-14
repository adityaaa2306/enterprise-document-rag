"""
Carbon-Aware Region Scheduling package.

Production-shaped architecture with one live execution region today
(Electricity Maps free-tier zone). Provider-agnostic and region-agnostic.

Application code should obtain grid intensity via::

    from src.carbon.scheduler import schedule_region
    decision = schedule_region(workload)

Do not call Electricity Maps directly from accounting or the orchestrator.
"""
from src.carbon.scheduler.models import (
    ExecutionRegion,
    GridCarbonData,
    RegionDecision,
    RegionStatus,
    WorkloadEstimate,
)
from src.carbon.scheduler.providers import (
    CarbonProvider,
    ElectricityMapsProvider,
    FutureCarbonProvider,
)
from src.carbon.scheduler.region_scheduler import (
    MODE_CARBON_OPTIMIZED,
    MODE_SINGLE_REGION,
    RegionScheduler,
    estimate_workload_from_state,
    get_region_scheduler,
    reset_region_scheduler_for_tests,
    schedule_region,
)
from src.carbon.scheduler.registry import (
    RegionRegistry,
    get_region_registry,
    reset_region_registry_for_tests,
)

__all__ = [
    "ExecutionRegion",
    "RegionStatus",
    "GridCarbonData",
    "RegionDecision",
    "WorkloadEstimate",
    "CarbonProvider",
    "ElectricityMapsProvider",
    "FutureCarbonProvider",
    "RegionRegistry",
    "get_region_registry",
    "reset_region_registry_for_tests",
    "RegionScheduler",
    "schedule_region",
    "get_region_scheduler",
    "reset_region_scheduler_for_tests",
    "estimate_workload_from_state",
    "MODE_SINGLE_REGION",
    "MODE_CARBON_OPTIMIZED",
]
