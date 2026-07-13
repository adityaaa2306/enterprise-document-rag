"""
Live Electricity Maps carbon-intensity client.

GET https://api.electricitymaps.com/v3/carbon-intensity/latest
Header: auth-token: <key>

Falls back to LOCAL_GRID_INTENSITY when the key is missing or the request fails.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from src.core.config import settings

log = logging.getLogger(__name__)

ELECTRICITY_MAPS_URL = "https://api.electricitymaps.com/v3/carbon-intensity/latest"


def fetch_grid_carbon_intensity(
    *,
    api_key: Optional[str] = None,
    zone: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    timeout_sec: float = 8.0,
) -> Dict[str, Any]:
    """
    Return grid intensity metadata.

    Keys:
      intensity_gco2_kwh, zone, datetime, updated_at, source, is_estimated
    """
    key = (api_key if api_key is not None else settings.ELECTRICITY_MAPS_API_KEY) or ""
    key = str(key).strip()
    z = (zone if zone is not None else getattr(settings, "ELECTRICITY_MAPS_ZONE", "") or "").strip()
    latitude = lat if lat is not None else float(getattr(settings, "ELECTRICITY_MAPS_LAT", 18.52) or 18.52)
    longitude = lon if lon is not None else float(getattr(settings, "ELECTRICITY_MAPS_LON", 73.85) or 73.85)

    fallback = {
        "intensity_gco2_kwh": float(getattr(settings, "LOCAL_GRID_INTENSITY", 700.0) or 700.0),
        "zone": z or "fallback",
        "datetime": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
        "source": "fallback_local_grid_intensity",
        "is_estimated": True,
        "error": None,
    }

    if not key or key.lower() in {"your_electricity_maps_key_here", "changeme"}:
        fallback["error"] = "ELECTRICITY_MAPS_API_KEY not set"
        log.warning("Electricity Maps: no API key — using LOCAL_GRID_INTENSITY=%.1f", fallback["intensity_gco2_kwh"])
        return fallback

    params: Dict[str, Any] = {}
    if z:
        params["zone"] = z
    else:
        params["lat"] = latitude
        params["lon"] = longitude

    try:
        resp = requests.get(
            ELECTRICITY_MAPS_URL,
            headers={"auth-token": key, "Accept": "application/json"},
            params=params,
            timeout=timeout_sec,
        )
        if resp.status_code != 200:
            fallback["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
            log.warning("Electricity Maps request failed: %s", fallback["error"])
            return fallback

        data = resp.json() if resp.content else {}
        intensity = data.get("carbonIntensity")
        if intensity is None:
            fallback["error"] = "missing carbonIntensity in response"
            log.warning("Electricity Maps: %s", fallback["error"])
            return fallback

        return {
            "intensity_gco2_kwh": float(intensity),
            "zone": str(data.get("zone") or z or "unknown"),
            "datetime": data.get("datetime"),
            "updated_at": data.get("updatedAt") or data.get("updated_at"),
            "source": "electricity_maps",
            "is_estimated": bool(data.get("isEstimated", False)),
            "estimation_method": data.get("estimationMethod"),
            "emission_factor_type": data.get("emissionFactorType"),
            "error": None,
            "raw": data,
        }
    except Exception as e:
        fallback["error"] = str(e)
        log.warning("Electricity Maps exception: %s — using fallback intensity", e)
        return fallback
