"""
Carbon scheduler facade.

All carbon numbers come from ``src.carbon.estimate_workflow_carbon``.
Legacy per-chunk gram constants have been removed.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.carbon import estimate_workflow_carbon
from src.carbon.electricity_maps import fetch_grid_carbon_intensity
from src.core.config import settings

log = logging.getLogger(__name__)


def get_grid_carbon_intensity(api_key: str = "", lat: float = 18.52, lon: float = 73.85) -> float:
    """Backward-compatible helper — prefer fetch_grid_carbon_intensity()."""
    info = fetch_grid_carbon_intensity(
        api_key=api_key or settings.ELECTRICITY_MAPS_API_KEY,
        lat=lat,
        lon=lon,
    )
    return float(info.get("intensity_gco2_kwh") or settings.LOCAL_GRID_INTENSITY)


def calculate_carbon_savings(job_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Workflow energy (kWh) × live Electricity Maps intensity → CO₂e (g).
    """
    log.info("Job %s: estimating workflow energy + Electricity Maps CO₂e...", job_id)
    return estimate_workflow_carbon(job_id, state)
