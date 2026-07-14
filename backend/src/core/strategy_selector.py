"""
Adaptive processing strategy selection from document capability + runtime context.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from src.core.config import settings
from src.core.document_capability import DocumentCapabilityProfile


@dataclass
class ProcessingStrategy:
    strategy_id: str
    map_mode: str  # single_pass | map_reduce | hierarchical_map | tree_summarize
    chunk_target_tokens: int
    hierarchy_fan_in: int
    hierarchy_max_depth: int
    skip_regional_below: int
    compile_depth_label: str  # none | flat | regional | chapter | multi_level
    medium_first: bool
    compile_tier_hint: str
    retrieval_strategy: str
    verification_strategy: str  # light | standard | strict
    qva_confidence_threshold: float
    qva_compile_threshold: float
    max_escalations: int
    max_escalate_chunks: int
    carbon_budget_g: float
    prefer_light_under_carbon: bool
    heavy_quality_gain_min: float
    reasons: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def select_processing_strategy(
    profile: DocumentCapabilityProfile,
    *,
    job_mode: str = "automatic",
    carbon_intensity: Optional[float] = None,
) -> ProcessingStrategy:
    """
    Choose an adaptive end-to-end strategy. Never a single fixed path.
    """
    mode = (job_mode or "automatic").lower()
    scale = profile.document_scale
    complexity = profile.complexity_class
    intensity = float(
        carbon_intensity
        if carbon_intensity is not None
        else getattr(settings, "LOCAL_GRID_INTENSITY", 700) or 700
    )
    reasons: list = [
        f"scale={scale}",
        f"complexity={complexity}",
        f"tokens={profile.estimated_tokens}",
        f"chunks={profile.chunk_count}",
        f"pages~{profile.pages_estimate}",
        f"grid_gco2={intensity:.0f}",
        f"mode={mode}",
    ]

    # --- Base by document scale ---
    if scale == "tiny":
        strategy = ProcessingStrategy(
            strategy_id="single_pass_compact",
            map_mode="single_pass",
            chunk_target_tokens=900,
            hierarchy_fan_in=16,
            hierarchy_max_depth=2,
            skip_regional_below=99,
            compile_depth_label="flat",
            medium_first=True,
            compile_tier_hint="medium",
            retrieval_strategy="hybrid_light",
            verification_strategy="light",
            qva_confidence_threshold=0.55,
            qva_compile_threshold=0.52,
            max_escalations=1,
            max_escalate_chunks=4,
            carbon_budget_g=float(settings.CARBON_BUDGET_G),
            prefer_light_under_carbon=True,
            heavy_quality_gain_min=0.03,
            reasons=reasons,
        )
        strategy.reasons.append("tiny doc → single-pass / flat compile")
    elif scale == "small":
        strategy = ProcessingStrategy(
            strategy_id="map_reduce_standard",
            map_mode="map_reduce",
            chunk_target_tokens=800,
            hierarchy_fan_in=10,
            hierarchy_max_depth=3,
            skip_regional_below=12,
            compile_depth_label="regional",
            medium_first=True,
            compile_tier_hint="medium",
            retrieval_strategy="hybrid",
            verification_strategy="standard",
            qva_confidence_threshold=0.58,
            qva_compile_threshold=0.55,
            max_escalations=2,
            max_escalate_chunks=6,
            carbon_budget_g=float(settings.CARBON_BUDGET_G),
            prefer_light_under_carbon=True,
            heavy_quality_gain_min=0.02,
            reasons=reasons,
        )
        strategy.reasons.append("small doc → map→reduce with light regional compile")
    elif scale == "medium":
        strategy = ProcessingStrategy(
            strategy_id="hierarchical_map_regional",
            map_mode="hierarchical_map",
            chunk_target_tokens=800,
            hierarchy_fan_in=8,
            hierarchy_max_depth=4,
            skip_regional_below=8,
            compile_depth_label="chapter",
            medium_first=True,
            compile_tier_hint="medium",
            retrieval_strategy="hybrid_rerank",
            verification_strategy="standard",
            qva_confidence_threshold=0.60,
            qva_compile_threshold=0.58,
            max_escalations=2,
            max_escalate_chunks=8,
            carbon_budget_g=float(settings.CARBON_BUDGET_G),
            prefer_light_under_carbon=True,
            heavy_quality_gain_min=0.02,
            reasons=reasons,
        )
        strategy.reasons.append("medium doc → hierarchical map + chapter compile")
    elif scale == "large":
        strategy = ProcessingStrategy(
            strategy_id="multi_level_tree",
            map_mode="tree_summarize",
            chunk_target_tokens=750,
            hierarchy_fan_in=10,
            hierarchy_max_depth=6,
            skip_regional_below=4,
            compile_depth_label="multi_level",
            medium_first=True,
            compile_tier_hint="heavy",
            retrieval_strategy="hybrid_rerank",
            verification_strategy="strict",
            qva_confidence_threshold=0.62,
            qva_compile_threshold=0.60,
            max_escalations=2,
            max_escalate_chunks=10,
            carbon_budget_g=float(settings.CARBON_BUDGET_G) * 1.25,
            prefer_light_under_carbon=True,
            heavy_quality_gain_min=0.015,
            reasons=reasons,
        )
        strategy.reasons.append("large doc → multi-level tree summarization")
    else:  # xlarge
        strategy = ProcessingStrategy(
            strategy_id="deep_tree_summarize",
            map_mode="tree_summarize",
            chunk_target_tokens=700,
            hierarchy_fan_in=12,
            hierarchy_max_depth=8,
            skip_regional_below=2,
            compile_depth_label="multi_level",
            medium_first=True,
            compile_tier_hint="heavy",
            retrieval_strategy="hybrid_rerank_aggressive",
            verification_strategy="strict",
            qva_confidence_threshold=0.64,
            qva_compile_threshold=0.62,
            max_escalations=3,
            max_escalate_chunks=12,
            carbon_budget_g=float(settings.CARBON_BUDGET_G) * 1.5,
            prefer_light_under_carbon=True,
            heavy_quality_gain_min=0.01,
            reasons=reasons,
        )
        strategy.reasons.append("xlarge doc → deep multi-level tree")

    # --- Complexity adjustments ---
    if complexity in ("complex", "critical"):
        strategy.verification_strategy = "strict"
        strategy.qva_confidence_threshold = min(0.72, strategy.qva_confidence_threshold + 0.04)
        strategy.compile_tier_hint = "heavy" if complexity == "critical" else strategy.compile_tier_hint
        strategy.max_escalate_chunks = min(16, strategy.max_escalate_chunks + 2)
        strategy.reasons.append(f"complexity={complexity} → stricter verification")
    elif complexity == "simple" and scale in ("tiny", "small"):
        strategy.verification_strategy = "light"
        strategy.prefer_light_under_carbon = True
        strategy.reasons.append("simple+small → prefer light models")

    # --- User mode ---
    if mode in ("fastest", "speed"):
        strategy.prefer_light_under_carbon = True
        strategy.max_escalations = max(1, strategy.max_escalations - 1)
        strategy.compile_tier_hint = "medium"
        strategy.medium_first = True
        strategy.reasons.append("user mode fastest → fewer escalations")
    elif mode in ("lowest_carbon", "eco", "green"):
        strategy.prefer_light_under_carbon = True
        strategy.carbon_budget_g *= 0.75
        strategy.heavy_quality_gain_min = max(strategy.heavy_quality_gain_min, 0.04)
        strategy.reasons.append("user mode eco → tighter carbon + higher heavy bar")
    elif mode in ("highest_quality", "quality"):
        strategy.verification_strategy = "strict"
        strategy.compile_tier_hint = "heavy"
        strategy.max_escalations = min(3, strategy.max_escalations + 1)
        strategy.prefer_light_under_carbon = False
        strategy.reasons.append("user mode quality → allow heavy more freely")

    # --- Live carbon intensity (never sole signal) ---
    if intensity >= 550:
        strategy.prefer_light_under_carbon = True
        strategy.reasons.append("high grid intensity → bias light/medium when quality allows")
    elif intensity <= 200:
        strategy.reasons.append("low grid intensity → carbon pressure reduced (quality still primary)")

    # Tables/figures: keep hierarchy a bit finer
    if profile.table_density >= 0.25 or profile.equation_count >= 8:
        strategy.hierarchy_fan_in = max(4, strategy.hierarchy_fan_in - 2)
        strategy.reasons.append("dense tables/equations → finer hierarchy fan-in")

    return strategy
