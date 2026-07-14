"""
Validation scenarios for redesigned carbon accounting.

Easy / medium / hard / all-heavy documents → baseline vs optimized report.
"""
from __future__ import annotations

from src.carbon.accounting import estimate_workflow_carbon


class _Chunk:
    def __init__(self, content: str):
        self.content = content


GRID = {
    "intensity_gco2_kwh": 700.0,
    "zone": "IN-WE",
    "source": "validation",
    "is_estimated": True,
}


def _state(n: int, tiers: list[str], compile_tier: str = "heavy") -> dict:
    body = ("Carbon-aware document processing with adaptive routing. " * 30)
    chunks = [_Chunk(body) for _ in range(n)]
    assert len(tiers) == n
    return {
        "chunks": chunks,
        "total_chunks": n,
        "chunks_escalated": 0,
        "final_summary": ("Executive summary of findings. " * 40),
        "model_usage_chars": {},
        "routing_decision": {
            "tier": tiers[0],
            "compile_tier": compile_tier,
            "selected_model": "test-model",
        },
        "chunk_routing": [
            {
                "chunk_index": i,
                "tier": tiers[i],
                "model": f"model-{tiers[i]}",
                "reason": "validation",
            }
            for i in range(n)
        ],
    }


def _print(label: str, report: dict) -> None:
    bd = report["breakdown"]
    ri = report["routing_impact"]
    print("=" * 64)
    print(label)
    print("-" * 64)
    print(f"  Baseline CO₂e (g):   {report['baseline_cost_gco2e']:.3f}")
    print(f"  Optimized CO₂e (g):  {report['actual_cost_gco2e']:.3f}")
    print(f"  Carbon Saved (g):    {report['carbon_saved_grams']:.3f}")
    print(f"  Reduction %:         {report['efficiency_percent']:+.1f}")
    print(f"  Direction:           {report['emissions_direction']}")
    print(
        f"  Routing L/M/H:       {ri['light_chunks']}/{ri['medium_chunks']}/{ri['heavy_chunks']}"
    )
    print(f"  Map tokens by tier:  {bd['map_tokens_by_tier']}")
    print(f"  Compile tier:        {bd['compile_tier']}")
    stages = bd["optimized_stages_gco2e"]
    print(
        f"  Stage inference/total: {stages.get('inference_gco2e'):.3f} / "
        f"{stages.get('total_gco2e'):.3f} g"
    )
    print(f"  Chunks in breakdown: {len(report['chunk_breakdown'])}")


def main() -> None:
    easy = estimate_workflow_carbon(
        "easy",
        _state(12, ["light"] * 12, compile_tier="medium"),
        grid=GRID,
    )
    medium = estimate_workflow_carbon(
        "medium",
        _state(
            12,
            ["light"] * 7 + ["medium"] * 4 + ["heavy"] * 1,
            compile_tier="heavy",
        ),
        grid=GRID,
    )
    hard = estimate_workflow_carbon(
        "hard",
        _state(12, ["medium"] * 4 + ["heavy"] * 8, compile_tier="heavy"),
        grid=GRID,
    )
    frontier = estimate_workflow_carbon(
        "all-heavy",
        _state(12, ["heavy"] * 12, compile_tier="heavy"),
        grid=GRID,
    )

    _print("EASY — mostly light (expect high savings)", easy)
    _print("MEDIUM — mixed routing (expect moderate savings)", medium)
    _print("HARD — mostly heavy (expect lower savings)", hard)
    _print("ALL-HEAVY — approaches baseline (routing stub may be slightly higher)", frontier)

    assert easy["carbon_saved_grams"] > medium["carbon_saved_grams"]
    assert medium["carbon_saved_grams"] > hard["carbon_saved_grams"]
    assert hard["carbon_saved_grams"] >= frontier["carbon_saved_grams"] - 0.01
    assert easy["efficiency_percent"] > 40
    # All-heavy should be near baseline (within a few percent due to routing stub)
    assert abs(frontier["efficiency_percent"]) < 5.0
    print("=" * 64)
    print("VALIDATION OK — ordering and near-baseline identity hold.")


if __name__ == "__main__":
    main()
