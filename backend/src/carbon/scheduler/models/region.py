"""Execution region registry models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class RegionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PLANNED = "PLANNED"


@dataclass(frozen=True)
class ExecutionRegion:
    """
    One deployable / scheduled execution region.

    Adding Finland / France / Singapore later is a registry entry + provider
    credentials — not a redesign of the scheduler algorithm.
    """

    id: str
    display_name: str
    provider: str
    grid_zone: str
    status: RegionStatus = RegionStatus.ACTIVE
    supports_execution: bool = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider": self.provider,
            "grid_zone": self.grid_zone,
            "status": self.status.value if isinstance(self.status, RegionStatus) else str(self.status),
            "supports_execution": bool(self.supports_execution),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "meta": dict(self.meta or {}),
        }
