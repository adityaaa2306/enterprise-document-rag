import os
import json
from io import BytesIO
from typing import Dict, Any, List

import requests
from requests.auth import HTTPBasicAuth
import PyPDF2

# Use absolute path relative to this file to find servers.json
current_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(current_dir, "servers.json"), "r", encoding="utf-8") as f:
    SERVER_CONFIG = json.load(f)

# Import settings from the same package
from .settings import WATTTIME_USERNAME, WATTTIME_PASSWORD

print(f"WATTTIME_USERNAME (after import): {WATTTIME_USERNAME}")
# print(f"WATTTIME_PASSWORD (after import): {WATTTIME_PASSWORD}") # Don't print password in logs

USE_WATTTIME = True # Force WattTime usage since credentials are provided in settings.py

# Simple mock intensities in gCO2/kWh for fallback/demo
MOCK_INTENSITY_BY_HINT = {
    "US-VA": 420.0,  # Virginia tends to be higher coal/gas share
    "IE": 300.0,     # Ireland moderate
    "US-OR": 250.0,  # Oregon cleaner hydro/wind
}
DEFAULT_MOCK_INTENSITY = 350.0


def _get_watttime_token() -> str | None:
    if not USE_WATTTIME:
        return None
    if not WATTTIME_USERNAME or not WATTTIME_PASSWORD:
        return None
    login_url = "https://api.watttime.org/login"
    rsp = requests.get(login_url, auth=HTTPBasicAuth(WATTTIME_USERNAME, WATTTIME_PASSWORD))
    print(f"WattTime login status: {rsp.status_code}")
    if rsp.status_code != 200:
        return None
    return rsp.json().get("token")


def _region_from_latlon(token: str, latitude: float, longitude: float) -> str:
    url = "https://api.watttime.org/v3/region-from-loc"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"latitude": str(latitude), "longitude": str(longitude), "signal_type": "co2_moer"}
    rsp = requests.get(url, headers=headers, params=params)
    rsp.raise_for_status()
    data = rsp.json()
    return data["region"]


def _get_current_moer(token: str, region: str) -> float:
    url = "https://api.watttime.org/v3/signal-index"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"region": region, "signal_type": "co2_moer"}
    rsp = requests.get(url, headers=headers, params=params)
    rsp.raise_for_status()

    try:
        f_url = "https://api.watttime.org/v3/forecast"
        f_params = {"region": region, "signal_type": "co2_moer", "horizon_hours": 0}
        f_rsp = requests.get(f_url, headers=headers, params=f_params)
        f_rsp.raise_for_status()
        f_data = f_rsp.json()
        values = f_data.get("data") or []
        if values:
            v = values[0].get("value")
            if isinstance(v, (int, float)):
                return (float(v) * 453.592) / 1000.0
    except Exception:
        pass

    idx = rsp.json().get("data")
    if isinstance(idx, list) and idx:
        idx_val = idx[0].get("value", 50)
    else:
        idx_val = 50
    return 200.0 + (500.0 * (float(idx_val) / 100.0))


def _get_mock_intensity(server: Dict[str, Any]) -> float:
    hint = server.get("region")
    if hint and hint in MOCK_INTENSITY_BY_HINT:
        return MOCK_INTENSITY_BY_HINT[hint]
    return DEFAULT_MOCK_INTENSITY


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extracts text from a PDF file given its path.
    """
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text_parts: List[str] = []
            for page in reader.pages:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception: 
                    continue
        return "\n".join(text_parts)
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""


def estimate_tokens_from_pdf(file_path: str) -> int:
    text = extract_text_from_pdf(file_path)
    char_count = len(text)
    # Rough estimate: 4 chars ~ 1 token
    estimated_tokens = char_count / 4.0
    return int(estimated_tokens + 100)


def calculate_carbon_footprint(tokens_needed: int, server_config: Dict[str, Any], carbon_intensity_g_per_kwh: float) -> Dict[str, float]:
    processing_time_seconds = tokens_needed / 1000.0
    energy_kwh = (server_config["base_power_watts"] * processing_time_seconds) / 3_600_000.0
    carbon_grams = energy_kwh * carbon_intensity_g_per_kwh
    return {
        "energy_kwh": energy_kwh,
        "carbon_grams": carbon_grams,
        "processing_time_seconds": processing_time_seconds,
    }


def generate_explanation(best: Dict[str, Any], all_options: List[Dict[str, Any]]) -> str:
    others = [o for o in all_options if o["server_id"] != best["server_id"]]
    if not others:
        return "Selected the only available server based on current grid intensity."
    
    second = sorted(others, key=lambda x: x["carbon_grams"])[0]
    saved = second["carbon_grams"] - best["carbon_grams"]
    return (
    f"{best['server_name']} has lower current grid carbon intensity ({best['carbon_intensity']:.0f} gCO2/kWh) "
    f"than {second['server_name']} ({second['carbon_intensity']:.0f} gCO2/kWh), saving ~{saved:.4f} g CO2 for this job."
)



def analyze_pdf_carbon_impact(pdf_file_path: str) -> Dict[str, Any]:
    """
    Analyzes the carbon impact of processing a PDF file efficiently.
    Accepts file path directly.
    """
    tokens_needed = estimate_tokens_from_pdf(pdf_file_path)

    print(f"Use WattTime: {USE_WATTTIME}")
    token = _get_watttime_token()
    using_mock = token is None
    recommendations: List[Dict[str, Any]] = []
    
    for server in SERVER_CONFIG["servers"]:
        if using_mock:
            carbon_intensity = _get_mock_intensity(server)
        else:
            try:
                # Use dynamic region lookup based on server coordinates
                region = _region_from_latlon(token, server["latitude"], server["longitude"])
                print(f"Server {server['name']}: Resolved region to {region}")
                carbon_intensity = _get_current_moer(token, region)
            except Exception as e:
                print(f"Error fetching real-time data for {server['name']}: {e}")
                carbon_intensity = _get_mock_intensity(server)

        impact = calculate_carbon_footprint(tokens_needed, server, carbon_intensity)
        recommendations.append(
            {
                "server_id": server["id"],
                "server_name": server["name"],
                "region": server.get("region", "Unknown"), # Added for schema mapping
                "carbon_grams": impact["carbon_grams"],
                "carbon_intensity": carbon_intensity,
                "energy_kwh": impact["energy_kwh"],
                "processing_time_seconds": impact["processing_time_seconds"],
                "cost_estimate": (tokens_needed / 1000.0) * float(server["cost_per_1k_tokens"]),
            }
        )

    if not recommendations:
        raise ValueError("No recommendations available. Check WattTime credentials and access.")

    best_server = min(recommendations, key=lambda x: x["carbon_grams"])

    return {
        "estimated_tokens": tokens_needed,
        "recommended_server": best_server,
        "all_options": sorted(recommendations, key=lambda x: x["carbon_grams"]),
        "explanation": generate_explanation(best_server, recommendations)
        + (" (using mock intensities)" if using_mock else ""),
        "data_source": "mock" if using_mock else "watttime",
    }
