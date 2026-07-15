"""
Ollama production soak: many nodes under concurrency with fallback checks.

Usage:
  cd backend
  python scripts/soak_ollama.py --docs 3 --chunks-per-doc 8
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=3)
    ap.add_argument("--chunks-per-doc", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    from src.core.config import settings
    from src.core import pipeline_executor as pe
    from src.agents import summarization_agents

    object.__setattr__(settings, "LLM_PROVIDER", "ollama")
    object.__setattr__(settings, "MAX_PARALLEL_WORKERS", args.workers)

    # Probe Ollama
    ollama_ok = False
    try:
        import httpx

        r = httpx.get(
            f"{getattr(settings, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/tags",
            timeout=5.0,
        )
        ollama_ok = r.status_code == 200
    except Exception as e:
        print(f"Ollama probe failed: {e}", flush=True)

    results: List[Dict[str, Any]] = []
    for d in range(args.docs):
        class C:
            def __init__(self, i):
                self.content = (
                    f"Doc {d} chunk {i}: Ollama soak paragraph about carbon-aware "
                    f"routing and hierarchical summarization quality checks. "
                ) * 20
                self.section_path = f"D{d}/S{i}"
                self.parent_id = f"d{d}"

        chunks = [C(i) for i in range(args.chunks_per_doc)]
        # Ollama first; NIM models follow so unavailable Ollama falls through the
        # same chain NIM would use (provider routing skips NIM ids when Ollama is
        # the global default).
        ollama_models = [
            "ollama/llama3.2",
            "ollama/llama3.1",
        ] + list(settings.medium_models())
        state: Dict[str, Any] = {
            "job_id": f"ollama-soak-{d}",
            "chunks": chunks,
            "chunk_routing": [
                {"chunk_index": i, "tier": "medium"} for i in range(len(chunks))
            ],
            "routing_decision": {
                "tier": "medium",
                "fallbacks": ollama_models,
            },
            "features": {"grid_intensity": 400.0},
            "pipeline_intelligence": {
                "strategy": {
                    "hierarchy_fan_in": 4,
                    "hierarchy_max_depth": 4,
                    "skip_regional_below": 0,
                    "qva_confidence_threshold": 0.4,
                    "qva_compile_threshold": 0.35,
                    "max_escalations": 1,
                    "medium_first": True,
                }
            },
        }
        # Per-chunk routes use the mixed chain
        for i in range(len(chunks)):
            state["chunk_routing"][i]["models"] = ollama_models

        # Monkeypatch chain_for_tier for this soak so map uses mixed chain
        from src.core import node_assigner as na

        monkey_chain = list(ollama_models)

        def _chain_for_tier(_tier: str, _chain=monkey_chain) -> List[str]:
            return list(_chain)

        na.chain_for_tier = _chain_for_tier  # type: ignore

        t0 = time.perf_counter()
        try:
            out = pe.execute_document_dag(state)
            wall = time.perf_counter() - t0
            tele = out.get("agent_telemetry") or []
            ok = sum(1 for t in tele if t.get("success"))
            results.append(
                {
                    "doc": d,
                    "ok": True,
                    "wall_sec": round(wall, 2),
                    "summaries_nonempty": sum(
                        1 for s in (out.get("summaries") or []) if (s or "").strip()
                    ),
                    "telemetry_ok": ok,
                    "telemetry_total": len(tele),
                    "final_len": len(str(out.get("final_summary") or "")),
                    "qva": out.get("validation_verdict"),
                    "provider_hint": "ollama",
                }
            )
        except Exception as e:
            results.append({"doc": d, "ok": False, "error": str(e)[:500]})
        print(results[-1], flush=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ollama_reachable": ollama_ok,
        "docs": args.docs,
        "chunks_per_doc": args.chunks_per_doc,
        "workers": args.workers,
        "results": results,
        "pass_rate": (
            sum(1 for r in results if r.get("ok")) / max(1, len(results))
        ),
    }
    out_path = ROOT / "eval_out" / "ollama_soak.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if not ollama_ok:
        print(
            "BLOCKER: Ollama not reachable — soak recorded probe failure; "
            "fallback path exercises require a running Ollama daemon.",
            flush=True,
        )


if __name__ == "__main__":
    main()
