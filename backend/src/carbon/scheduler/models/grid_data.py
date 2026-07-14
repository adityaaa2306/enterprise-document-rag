"""Grid intensity payload returned by carbon providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class GridCarbonData:
    """
    Provider-agnostic live (or fallback) grid carbon intensity for a region.
    """

    intensity_gco2_kwh: float
    zone: str
    provider: str
    source: str
    datetime: Optional[str] = None
    updated_at: Optional[str] = None
    is_estimated: bool = False
    data_freshness: str = "unknown"  # live | cached | fallback | unknown
    confidence: str = "medium"  # high | medium | low
    error: Optional[str] = None
    cache_hit: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Shape expected by existing accounting / UI (pre-scheduler)."""
        return {
            "intensity_gco2_kwh": float(self.intensity_gco2_kwh),
            "zone": self.zone,
            "datetime": self.datetime,
            "updated_at": self.updated_at,
            "source": self.source,
            "is_estimated": bool(self.is_estimated),
            "error": self.error,
            "cache_hit": bool(self.cache_hit),
            "provider": self.provider,
            "data_freshness": self.data_freshness,
            "confidence": self.confidence,
            "raw": dict(self.raw or {}),
        }

    @classmethod
    def from_legacy_dict(cls, raw: Dict[str, Any], *, provider: str = "unknown") -> "GridCarbonData":
        source = str(raw.get("source") or "unknown")
        cache_hit = bool(raw.get("cache_hit"))
        if source == "electricity_maps" and not cache_hit:
            freshness = "live"
            confidence = "high"
        elif source == "electricity_maps" and cache_hit:
            freshness = "cached"
            confidence = "high"
        elif "fallback" in source:
            freshness = "fallback"
            confidence = "low"
        else:
            freshness = str(raw.get("data_freshness") or "unknown")
            confidence = str(raw.get("confidence") or "medium")
        return cls(
            intensity_gco2_kwh=float(raw.get("intensity_gco2_kwh") or 0.0),
            zone=str(raw.get("zone") or "unknown"),
            provider=str(raw.get("provider") or provider),
            source=source,
            datetime=raw.get("datetime"),
            updated_at=raw.get("updated_at"),
            is_estimated=bool(raw.get("is_estimated", False)),
            data_freshness=freshness,
            confidence=confidence,
            error=raw.get("error"),
            cache_hit=cache_hit,
            raw=dict(raw.get("raw") or {}) if isinstance(raw.get("raw"), dict) else {},
        )
