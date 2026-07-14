"""Region registry — configuration-driven, not hardcoded in business logic."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.carbon.scheduler.models.region import ExecutionRegion, RegionStatus
from src.core.config import settings

log = logging.getLogger(__name__)


def _default_india_region() -> ExecutionRegion:
    """
    Build the single live execution region from settings.

    India is the default *configured* region (Electricity Maps free-tier zone),
    not a hard-coded choice inside the scheduling algorithm.
    """
    zone = str(getattr(settings, "ELECTRICITY_MAPS_ZONE", "") or "").strip()
    provider = str(
        getattr(settings, "REGION_SCHEDULER_PROVIDER", "electricity_maps") or "electricity_maps"
    ).strip()
    region_id = str(
        getattr(settings, "REGION_SCHEDULER_DEFAULT_REGION", "india") or "india"
    ).strip().lower()
    display = str(
        getattr(settings, "REGION_SCHEDULER_DEFAULT_REGION_NAME", "India") or "India"
    ).strip()
    lat = float(getattr(settings, "ELECTRICITY_MAPS_LAT", 18.52) or 18.52)
    lon = float(getattr(settings, "ELECTRICITY_MAPS_LON", 73.85) or 73.85)
    return ExecutionRegion(
        id=region_id,
        display_name=display,
        provider=provider,
        grid_zone=zone,  # empty → lat/lon resolution (IN-WE / Pune defaults)
        status=RegionStatus.ACTIVE,
        supports_execution=True,
        latitude=lat,
        longitude=lon,
        meta={
            "notes": "Single live region on Electricity Maps free tier",
            "default_lat_lon_hint": "Pune / western India when zone empty",
        },
    )


class RegionRegistry:
    """
    Holds execution regions. Today: one ACTIVE region.
    Tomorrow: register Finland / France / Singapore without redesign.
    """

    def __init__(self, regions: Optional[List[ExecutionRegion]] = None) -> None:
        self._regions: Dict[str, ExecutionRegion] = {}
        for r in regions or [_default_india_region()]:
            self.register(r)

    def register(self, region: ExecutionRegion) -> None:
        self._regions[region.id.lower()] = region
        log.debug("RegionRegistry: registered %s (%s)", region.id, region.status)

    def get(self, region_id: str) -> Optional[ExecutionRegion]:
        return self._regions.get(str(region_id or "").strip().lower())

    def list_regions(self) -> List[ExecutionRegion]:
        return list(self._regions.values())

    def active_executable(self) -> List[ExecutionRegion]:
        return [
            r
            for r in self._regions.values()
            if r.status == RegionStatus.ACTIVE and r.supports_execution
        ]

    def default_region(self) -> ExecutionRegion:
        configured = str(
            getattr(settings, "REGION_SCHEDULER_DEFAULT_REGION", "india") or "india"
        ).strip().lower()
        region = self.get(configured)
        if region and region.supports_execution and region.status == RegionStatus.ACTIVE:
            return region
        active = self.active_executable()
        if not active:
            raise RuntimeError("RegionRegistry has no ACTIVE executable regions")
        return active[0]


_REGISTRY: Optional[RegionRegistry] = None


def get_region_registry() -> RegionRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = RegionRegistry()
    return _REGISTRY


def reset_region_registry_for_tests() -> None:
    global _REGISTRY
    _REGISTRY = None
