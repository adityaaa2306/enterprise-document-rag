"""
Workflow-level operational carbon accounting (Boundary A).

Pipeline (single source of truth for jobs, dashboard, reports):

  Tokens × J/token → × PUE → kWh → Electricity Maps intensity → CO₂e (g)

Never multiply tokens/chunks/pages by a carbon factor directly.
Never apply silent calibration multipliers (e.g. removed BASELINE_SERVING_OVERHEAD).
"""
from __future__ import annotations

from src.carbon.accounting import (
    ASSUMPTIONS_PANEL_TEXT,
    METHODOLOGY_TEXT,
    estimate_workflow_carbon,
)
from src.carbon.assumptions import (
    DEFAULT_REPORTING_BOUNDARY,
    PUE,
    ReportingBoundary,
    assumption_snapshot,
)
from src.carbon.electricity_maps import fetch_grid_carbon_intensity
from src.carbon.energy_model import estimate_tokens

__all__ = [
    "estimate_workflow_carbon",
    "fetch_grid_carbon_intensity",
    "estimate_tokens",
    "METHODOLOGY_TEXT",
    "ASSUMPTIONS_PANEL_TEXT",
    "PUE",
    "ReportingBoundary",
    "DEFAULT_REPORTING_BOUNDARY",
    "assumption_snapshot",
]
