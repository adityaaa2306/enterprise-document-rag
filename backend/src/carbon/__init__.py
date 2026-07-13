"""
Workflow-level carbon accounting.

Pipeline (single source of truth for jobs, dashboard, reports):

  Workflow stages → Energy (kWh) → Electricity Maps intensity → CO₂e (g)

Never multiply tokens/chunks/pages by a carbon factor directly.
"""
from __future__ import annotations

from src.carbon.accounting import estimate_workflow_carbon, METHODOLOGY_TEXT
from src.carbon.electricity_maps import fetch_grid_carbon_intensity
from src.carbon.energy_model import estimate_tokens

__all__ = [
    "estimate_workflow_carbon",
    "fetch_grid_carbon_intensity",
    "estimate_tokens",
    "METHODOLOGY_TEXT",
]
