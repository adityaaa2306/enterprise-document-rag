"""Region scheduling decision object."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.carbon.scheduler.models.grid_data import GridCarbonData
from src.carbon.scheduler.models.region import ExecutionRegion


@dataclass
class WorkloadEstimate:
    """
    Lightweight workload signal for the region scheduler.

    Independent of model routing — token/chunk counts only.
    Single-region mode records this for telemetry; carbon-optimized mode
    (future) may use it for multi-region cost estimation.
    """

    job_id: Optional[str] = None
    estimated_tokens: int = 0
    estimated_chunks: int = 0
    document_chars: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "estimated_tokens": int(self.estimated_tokens),
            "estimated_chunks": int(self.estimated_chunks),
            "document_chars": int(self.document_chars),
            "meta": dict(self.meta or {}),
        }


@dataclass
class RegionDecision:
    """
    Every region scheduling decision returns this object.

    Honest about single-region mode — never claims global optimization
    when only one live execution region is configured.
    """

    selected_region: ExecutionRegion
    reason: str
    grid: GridCarbonData
    provider: str
    scheduling_mode: str
    timestamp: str
    data_freshness: str
    confidence: str
    execution_status: str = "configured_region"
    future_support: str = "multi_region_scheduling"
    workload: Optional[WorkloadEstimate] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_region": self.selected_region.to_dict(),
            "selected_region_id": self.selected_region.id,
            "selected_region_name": self.selected_region.display_name,
            "reason": self.reason,
            "grid_carbon_intensity_gco2_kwh": float(self.grid.intensity_gco2_kwh),
            "grid_zone": self.grid.zone,
            "provider": self.provider,
            "scheduling_mode": self.scheduling_mode,
            "timestamp": self.timestamp,
            "data_freshness": self.data_freshness,
            "confidence": self.confidence,
            "execution_status": self.execution_status,
            "future_support": self.future_support,
            "data_source": (
                "live"
                if self.data_freshness == "live"
                else (
                    "cached"
                    if self.data_freshness == "cached"
                    else (
                        "fallback"
                        if self.data_freshness == "fallback"
                        else self.data_freshness
                    )
                )
            ),
            "workload": self.workload.to_dict() if self.workload else None,
            "meta": dict(self.meta or {}),
            "grid": self.grid.to_legacy_dict(),
        }

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
