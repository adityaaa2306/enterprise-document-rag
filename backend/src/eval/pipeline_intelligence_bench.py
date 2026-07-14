"""
Benchmark harness for adaptive pipeline intelligence (scale simulation).

Does NOT call live LLMs. Simulates document sizes and reports strategy choices,
hierarchy depth, estimated map calls / carbon / latency.

Usage:
  python -m src.eval.pipeline_intelligence_bench
"""
from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any, Dict, List

from src.core.document_capability import analyze_document_capability
from src.core.hierarchy import build_hierarchy_levels
from src.core.pipeline_intelligence import plan_pipeline_intelligence
from src.core.strategy_selector import select_processing_strategy


def _make_doc(pages: int, tokens_per_page: int = 500) -> List[Any]:
    """Synthetic chunks approximating a document of `pages` pages."""
    total_tokens = pages * tokens_per_page
    # ~800 tokens per chunk target
    n_chunks = max(1, total_tokens // 800)
    word = "methodology evaluation carbon latency retrieval "
    # ~1 token ≈ 4 chars; word ~40 chars ≈ 10 tokens
    words_needed = max(20, (total_tokens // n_chunks) // 10)
    body = word * words_needed
    chunks = []
    for i in range(n_chunks):
        chunks.append(
            SimpleNamespace(
                content=f"Chapter {i+1}. {body}",
                chunk_index=i,
                parent_id=f"sec_{i}",
                section_path=f"Chapter {i+1}",
                type="Text",
                chunk_kind="merged",
            )
        )
    return chunks


SCENARIOS = [
    ("10-page report", 10),
    ("50-page report", 50),
    ("200-page report", 200),
    ("700-page report", 700),
]


def run_benchmark() -> List[Dict[str, Any]]:
    rows = []
    for name, pages in SCENARIOS:
        chunks = _make_doc(pages)
        features = {
            "reasoning_score": 0.55 if pages < 100 else 0.7,
            "structural_score": 0.5,
            "coherence_score": 0.45,
            "document_type": "technical_documentation",
            "risk_level": "technical",
        }
        chunk_feats = [
            {
                "chunk_index": i,
                "complexity": 0.5,
                "importance": 0.5,
                "technical_density": 0.45,
                "token_count": 800,
            }
            for i in range(len(chunks))
        ]
        intel = plan_pipeline_intelligence(
            chunks=chunks,
            features=features,
            chunk_features=chunk_feats,
            triage_meta={
                "section_count": len(chunks),
                "structure_diagnostics": {
                    "merged_sections": len(chunks),
                    "packed_chunks": len(chunks),
                },
            },
            job_mode="automatic",
            carbon_intensity=572,
        )
        profile = intel["capability_profile"]
        strat = intel["strategy"]
        report = intel["report"]
        summaries = [f"Summary of chapter {i}" for i in range(len(chunks))]
        levels = build_hierarchy_levels(
            chunks,
            summaries,
            fan_in=int(strat["hierarchy_fan_in"]),
            max_depth=int(strat["hierarchy_max_depth"]),
            skip_regional_below=int(strat["skip_regional_below"]),
        )
        rows.append(
            {
                "scenario": name,
                "pages": pages,
                "chunk_count": profile["chunk_count"],
                "estimated_tokens": profile["estimated_tokens"],
                "document_scale": profile["document_scale"],
                "complexity_class": profile["complexity_class"],
                "strategy_id": strat["strategy_id"],
                "map_mode": strat["map_mode"],
                "compile_depth": strat["compile_depth_label"],
                "hierarchy_depth": len(levels),
                "fan_in": strat["hierarchy_fan_in"],
                "map_api_calls": report["estimated_map_api_calls"],
                "est_carbon_g": report["estimated_carbon_g"],
                "est_latency_s": report["estimated_latency_s"],
                "expected_quality": report["expected_quality"],
                "verification": strat["verification_strategy"],
            }
        )
    return rows


def main():
    rows = run_benchmark()
    print(json.dumps(rows, indent=2))
    print("\n=== Summary ===")
    for r in rows:
        print(
            f"{r['scenario']:18} scale={r['document_scale']:7} "
            f"strategy={r['strategy_id']:28} chunks={r['chunk_count']:4} "
            f"depth={r['hierarchy_depth']} carbon~{r['est_carbon_g']}g "
            f"latency~{r['est_latency_s']}s"
        )


if __name__ == "__main__":
    main()
