"""Electricity Maps carbon intensity provider (current live provider)."""
from __future__ import annotations

import logging
from typing import Optional

from src.carbon.electricity_maps import fetch_grid_carbon_intensity
from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.models.region import ExecutionRegion
from src.carbon.scheduler.providers.carbon_provider import CarbonProvider

log = logging.getLogger(__name__)


class ElectricityMapsProvider(CarbonProvider):
    """
    Live Electricity Maps intensity for the region's configured zone / lat-lon.

    Behaviour matches the pre-scheduler client: live fetch with LOCAL_GRID fallback.
    No simulated worldwide routing.
    """

    provider_id = "electricity_maps"

    def __init__(self, *, api_key: Optional[str] = None, timeout_sec: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout_sec = timeout_sec

    def get_grid_intensity(self, region: ExecutionRegion) -> GridCarbonData:
        zone = (region.grid_zone or "").strip()
        lat = region.latitude
        lon = region.longitude
        # Empty zone → provider uses lat/lon (same as legacy ELECTRICITY_MAPS_ZONE="")
        raw = fetch_grid_carbon_intensity(
            api_key=self._api_key,
            zone=zone or None,
            lat=lat,
            lon=lon,
            timeout_sec=self._timeout_sec,
        )
        data = GridCarbonData.from_legacy_dict(raw, provider=self.provider_id)
        log.debug(
            "ElectricityMapsProvider region=%s zone=%s intensity=%.1f source=%s",
            region.id,
            data.zone,
            data.intensity_gco2_kwh,
            data.source,
        )
        return data
