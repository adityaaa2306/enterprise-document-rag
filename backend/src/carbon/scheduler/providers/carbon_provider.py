"""Carbon intensity provider abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.models.region import ExecutionRegion


class CarbonProvider(ABC):
    """
    Region Scheduler never knows whether intensity comes from Electricity Maps,
    a historical cache, a forecast API, or another source — only the provider does.
    """

    provider_id: str = "abstract"

    @abstractmethod
    def get_grid_intensity(self, region: ExecutionRegion) -> GridCarbonData:
        """Return grid carbon intensity for the given execution region."""

    def healthcheck(self) -> bool:
        return True
