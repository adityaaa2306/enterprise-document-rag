"""
Carbon scheduler facade (legacy module name).

Workflow CO₂e still comes from ``estimate_workflow_carbon``.
Live grid intensity is obtained via the Carbon-Aware Region Scheduler
(``src.carbon.scheduler``), not by calling Electricity Maps from here.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.carbon import estimate_workflow_carbon
from src.carbon.scheduler import schedule_region
from src.core.config import settings

log = logging.getLogger(__name__)


def get_grid_carbon_intensity(api_key: str = "", lat: float = 18.52, lon: float = 73.85) -> float:
    """
    Backward-compatible helper — prefer RegionScheduler.schedule().

    ``api_key`` / ``lat`` / ``lon`` are accepted for API compatibility but the
    configured region registry + provider are the source of truth.
    """
    _ = (api_key, lat, lon)  # legacy signature
    decision = schedule_region()
    return float(
        decision.grid.intensity_gco2_kwh
        or getattr(settings, "LOCAL_GRID_INTENSITY", 700.0)
        or 700.0
    )


def calculate_carbon_savings(job_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Workflow energy (kWh) × region-scheduler grid intensity → CO₂e (g).
    """
    log.info(
        "Job %s: estimating workflow energy + region-scheduler CO₂e...",
        job_id,
    )
    return estimate_workflow_carbon(job_id, state)
