"""
Placeholder for a future alternate carbon-intensity provider.

Not registered by default. Adding a second provider later means implementing
CarbonProvider and registering it — not changing RegionScheduler logic.
"""
from __future__ import annotations

from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.models.region import ExecutionRegion
from src.carbon.scheduler.providers.carbon_provider import CarbonProvider


class FutureCarbonProvider(CarbonProvider):
    """Stub — raises until a real forecast / historical provider is wired."""

    provider_id = "future_provider"

    def get_grid_intensity(self, region: ExecutionRegion) -> GridCarbonData:
        raise NotImplementedError(
            "FutureCarbonProvider is a placeholder for multi-provider extension. "
            f"Requested region={region.id}."
        )
