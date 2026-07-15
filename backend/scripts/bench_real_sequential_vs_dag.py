"""
Real Sequential vs Parallel DAG benchmark against live NIM (and optional Ollama).

Usage:
  cd backend
  python scripts/bench_real_sequential_vs_dag.py
  python scripts/bench_real_sequential_vs_dag.py --sizes 4,8,16 --provider nim
  python scripts/bench_real_sequential_vs_dag.py --provider ollama --sizes 4,8

Writes:
  backend/eval_out/sequential_vs_dag_real.json
  frontend/data/sequential_vs_dag.json  (landing page source of truth)
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


def _make_chunks(n: int):
    class C:
        def __init__(self, i):
            self.content = (
                f"Section {i}: Carbon-aware retrieval and hierarchical summarization. "
                f"Key finding {i % 7}: renewable intensity and model routing trade-offs. "
            ) * 12
            self.section_path = f"Sec{i // 4}"
            self.parent_id = f"p{i // 4}"

    return [C(i) for i in range(n)]


def _fake_summaries(n: int) -> List[str]:
    return [
        f"Summary of chunk {i}: covers renewable routing, latency, and carbon for topic {i % 7}."
        for i in range(n)
    ]


def _run_mode(
    *,
    n_chunks: int,
    workers: int,
    sequential: bool,
    provider: str,
) -> Dict[str, Any]:
    from src.core import dag_scheduler
    from src.core.config import settings

    if provider == "ollama":
        object.__setattr__(settings, "LLM_PROVIDER", "ollama")
    else:
        object.__setattr__(settings, "LLM_PROVIDER", "openai_compatible")

    chunks = _make_chunks(n_chunks)
    summaries = _fake_summaries(n_chunks)
    state: Dict[str, Any] = {
        "model_usage_chars": {"light": 0, "medium": 0, "large": 0},
        "models_used": [],
        "features": {"grid_intensity": 450.0},
        "job_id": f"bench-{'seq' if sequential else 'dag'}-{n_chunks}",
    }

    t0 = time.perf_counter()
    out = dag_scheduler.run_dag_compile(
        chunks,
        summaries,
        state,
        fan_in=4 if not sequential else max(n_chunks, 2),
        max_depth=8,
        skip_regional_below=0,
        medium_chain=list(settings.medium_models()),
        heavy_chain=list(settings.heavy_models()),
        medium_first=True,
        qva_tau=0.35,
        max_workers=1 if sequential else workers,
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    nodes = out.get("dag_nodes") or {}
    latencies = [
        float(n.get("latency_ms") or 0)
        for n in nodes.values()
        if isinstance(n, dict) and n.get("kind") != "chunk"
    ]
    return {
        "mode": "sequential" if sequential else "parallel_dag",
        "provider": provider,
        "chunks": n_chunks,
        "workers": 1 if sequential else workers,
        "wall_ms": round(wall_ms, 1),
        "compile_calls": out.get("compile_calls"),
        "carbon_g": round(float(out.get("compile_carbon_g") or 0.0), 4),
        "final_len": len(str(out.get("final_summary") or "")),
        "avg_node_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "critical_path_ms": round(max(latencies), 1) if latencies else None,
        "used_heavy": bool(out.get("used_heavy")),
        "qva_hint": "live_models",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="4,8,16", help="comma-separated chunk counts")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--provider", choices=["nim", "ollama", "both"], default="nim")
    ap.add_argument("--skip-frontend-copy", action="store_true")
    args = ap.parse_args()
    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    providers = ["nim", "ollama"] if args.provider == "both" else [args.provider]

    rows: List[Dict[str, Any]] = []
    for prov in providers:
        for n in sizes:
            print(f"=== {prov} sequential n={n} ===", flush=True)
            seq = _run_mode(n_chunks=n, workers=args.workers, sequential=True, provider=prov)
            print(f"=== {prov} parallel n={n} ===", flush=True)
            par = _run_mode(n_chunks=n, workers=args.workers, sequential=False, provider=prov)
            speedup = (seq["wall_ms"] / par["wall_ms"]) if par["wall_ms"] > 0 else 0.0
            rows.append(
                {
                    "provider": prov,
                    "chunks": n,
                    "sequential_wall_ms": seq["wall_ms"],
                    "parallel_wall_ms": par["wall_ms"],
                    "speedup": round(speedup, 2),
                    "sequential_carbon_g": seq["carbon_g"],
                    "parallel_carbon_g": par["carbon_g"],
                    "parallel_avg_latency_ms": par["avg_node_latency_ms"],
                    "parallel_critical_path_ms": par["critical_path_ms"],
                    "workers": args.workers,
                    "seq_detail": seq,
                    "par_detail": par,
                }
            )
            print(
                f"n={n} provider={prov} seq={seq['wall_ms']:.0f}ms "
                f"par={par['wall_ms']:.0f}ms speedup={speedup:.2f}x",
                flush=True,
            )

    nim_rows = [r for r in rows if r["provider"] == "nim"] or rows
    speedups = [r["speedup"] for r in nim_rows]
    median = sorted(speedups)[len(speedups) // 2] if speedups else 0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Measured against live model providers (not stubbed NIM).",
        "headline": {
            "median_speedup": round(median, 2),
            "best_speedup": round(max(speedups), 2) if speedups else 0,
            "label": "vs sequential reduce · live NIM",
        },
        "rows": [
            {
                "chunks": r["chunks"],
                "sequential_wall_ms": r["sequential_wall_ms"],
                "parallel_wall_ms": r["parallel_wall_ms"],
                "speedup": r["speedup"],
                "sequential_carbon_g": r["sequential_carbon_g"],
                "parallel_carbon_g": r["parallel_carbon_g"],
                "provider": r["provider"],
            }
            for r in rows
        ],
        "full": rows,
    }

    out_dir = ROOT / "eval_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sequential_vs_dag_real.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Landing page consumes sequential_vs_dag.json
    landing = out_dir / "sequential_vs_dag.json"
    landing.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}", flush=True)

    if not args.skip_frontend_copy:
        fe = ROOT.parent / "frontend" / "data" / "sequential_vs_dag.json"
        fe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(landing, fe)
        print(f"Copied to {fe}", flush=True)


if __name__ == "__main__":
    main()
