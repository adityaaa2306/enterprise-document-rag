import logging
import requests
from typing import Dict, Any, Optional

from src.core.config import settings

log = logging.getLogger(__name__)

# --- MODEL CARBON COST (SIMULATED) ---
# These are *estimates* of the gCO2e (grams of CO2 equivalent) *per chunk*.
# These are the basis of our "Green-Agentic" metric.
CARBON_COSTS_PER_CHUNK_GCO2E = {
    # (Triage) - Base cost for just parsing the document
    "triage_hi_res": 0.05,  # Visual, agentic parsing has a cost
    "triage_fast": 0.01,    # Simple text parsing is cheaper

    # (Summarize) - The core "green" tradeoff
    # Light model is extremely cheap per unit of text processed
    "summarize_light": 0.005, 
    "summarize_medium": 0.05, # Medium model is 10x more expensive
    "summarize_large": 0.5,   # Large model is 100x more expensive

    # (Accuracy Check) - A very fast, cheap NLI model
    "check_accuracy": 0.005,
    
    # (RAG)
    "embedding": 0.01,
}

# This is our "Baseline" - what a "dumb" system would do.
# It assumes a powerful 'Large' model is used for *every single chunk*.
BASELINE_COST_PER_CHUNK = (
    CARBON_COSTS_PER_CHUNK_GCO2E["triage_hi_res"] + 
    CARBON_COSTS_PER_CHUNK_GCO2E["summarize_large"]
)


def get_grid_carbon_intensity(api_key: str, lat: float = 18.52, lon: float = 73.85) -> float:
    """
    Gets the *real* carbon intensity (gCO2eq/kWh) for a location.
    
    NOTE: We are simulating this with a hard-coded value from settings
    to avoid requiring an API key for the "No-Docker" setup.
    """
    if not api_key or api_key == "YOUR_ELECTRICITY_MAPS_KEY_HERE":
        log.warning("ELECTRICITY_MAPS_API_KEY not set. Using simulated local grid intensity.")
        # This is the high-carbon simulation for your local grid
        return settings.LOCAL_GRID_INTENSITY

    # For our "No-Docker" build, we just return the simulated value
    # In production, this is where the API call happens.
    return settings.LOCAL_GRID_INTENSITY


# --- THE CORRECTED FUNCTION SIGNATURE ---
def calculate_carbon_savings(job_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    This is the core function that calculates the "green-ness" of our agent.
    It uses the model usage stats collected during the LangGraph run.
    """
    
    # Retrieve metrics from the state dictionary
    total_chunks = state.get("total_chunks", 1)
    chunks_escalated = state.get("chunks_escalated", 0)
    model_usage_chars = state.get("model_usage_chars", {})
    
    log.info(f"Job {job_id}: Calculating carbon savings for {total_chunks} chunks...")

    # 1. Get the real-time (or simulated) grid intensity
    local_grid_gco2_kwh = get_grid_carbon_intensity(settings.ELECTRICITY_MAPS_API_KEY)
    
    # 2. Calculate the carbon cost of the "Baseline" (dumb) method
    # This is what our system *avoided* doing. (Assumes Large Model is run total_chunks times)
    baseline_cost_gco2e = BASELINE_COST_PER_CHUNK * total_chunks
    
    # 3. Calculate the *actual* carbon cost of our agentic (MoE) job
    
    # Cost of Triage and Accuracy Check (happens once per chunk)
    cost_triage_and_check = (
        CARBON_COSTS_PER_CHUNK_GCO2E["triage_hi_res"] + 
        CARBON_COSTS_PER_CHUNK_GCO2E["check_accuracy"]
    ) * total_chunks
    
    # Cost for Light Summarization (most chunks) - based on CHUNK count
    # We run the light model on ALL chunks initially
    cost_light_summarization = (
        total_chunks * CARBON_COSTS_PER_CHUNK_GCO2E["summarize_light"]
    )
    
    # Cost for Medium Summarization (escalated chunks) - based on CHUNK count
    cost_medium_summarization = (
        chunks_escalated * CARBON_COSTS_PER_CHUNK_GCO2E["summarize_medium"]
    )
    
    # Cost for Final Compile (happens only once)
    # The cost is high because it's running the Large Model
    cost_final_compile = CARBON_COSTS_PER_CHUNK_GCO2E["summarize_large"] * 1
    
    actual_cost_gco2e = (
        cost_triage_and_check + 
        cost_light_summarization + 
        cost_medium_summarization + 
        cost_final_compile
    )
    
    # 4. Calculate the savings
    carbon_saved_grams = baseline_cost_gco2e - actual_cost_gco2e
    
    if baseline_cost_gco2e > 0:
        # Calculate how much more efficient we were
        efficiency_percent = (carbon_saved_grams / baseline_cost_gco2e) * 100
    else:
        efficiency_percent = 0

    message = f"Saved {carbon_saved_grams:.2f}g CO2e ({efficiency_percent:.0f}% more efficient) by using 'Light' models first."
    log.info(f"Job {job_id}: {message}")

    return {
        "carbon_saved_grams": carbon_saved_grams,
        "baseline_cost_gco2e": baseline_cost_gco2e,
        "actual_cost_gco2e": actual_cost_gco2e,
        "efficiency_percent": efficiency_percent,
        "message": message,
        "local_grid_gco2_kwh": local_grid_gco2_kwh,
        "compute_location": "local_hybrid",
        "total_chunks": total_chunks,
        "chunks_escalated": chunks_escalated
    }