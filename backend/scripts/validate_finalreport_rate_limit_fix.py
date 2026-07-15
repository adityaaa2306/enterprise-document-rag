"""
Validate rate-limit backoff fix on FinalReport.pdf (live NIM).

Usage:
  cd backend
  python scripts/validate_finalreport_rate_limit_fix.py
"""
from __future__ import annotations

import json
import shutil
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from src.agents import triage, models
    from src.chunking import ChunkingService
    from src.core.config import settings
    from src.core.pipeline_executor import execute_document_dag
    from src.core.nim_rate_limit import rate_limit_stats, reset_rate_limit_stats

    pdf = REPO / "FinalReport.pdf"
    assert pdf.exists(), f"Missing {pdf}"

    # Ensure limiter is on for this validation
    object.__setattr__(settings, "NIM_RATE_LIMITER_ENABLED", True)
    if not float(getattr(settings, "NIM_MAX_REQUESTS_PER_MINUTE", 0) or 0):
        object.__setattr__(settings, "NIM_MAX_REQUESTS_PER_MINUTE", 30.0)

    models.load_nim_client()
    reset_rate_limit_stats()
    tracemalloc.start()
    t0 = time.perf_counter()

    print(f"Triaging {pdf}...", flush=True)
    raw = triage.triage_document(str(pdf), "pdf", settings.TRIAGE_STRATEGY)
    chunks, _parents, meta = ChunkingService().build(raw, document_id="finalreport-rl-fix")
    print(
        f"raw_blocks={len(raw)} adaptive_chunks={len(chunks)} meta_chunk_count={meta.get('chunk_count')}",
        flush=True,
    )

    state: Dict[str, Any] = {
        "job_id": "finalreport-rate-limit-fix",
        "chunks": chunks,
        "total_chunks": len(chunks),
        "chunk_routing": [
            {"chunk_index": i, "tier": "light"} for i in range(len(chunks))
        ],
        "routing_decision": {
            "tier": "light",
            "selected_model": settings.light_models()[0],
            "fallbacks": list(settings.light_models()),
        },
        "features": {"grid_intensity": float(settings.LOCAL_GRID_INTENSITY)},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 6,
                "hierarchy_max_depth": 8,
                "skip_regional_below": 0,
                "qva_confidence_threshold": 0.5,
                "qva_compile_threshold": 0.45,
                "max_escalations": 1,
                "max_escalate_chunks": 4,
                "medium_first": True,
            }
        },
        "carbon_spent_g": 0.0,
        "agent_telemetry": [],
    }

    def pcb(pct, msg, extra):
        print(f"[{time.perf_counter() - t0:7.1f}s] {pct:5.1f}% {msg}", flush=True)

    out = execute_document_dag(state, progress_cb=pcb)
    wall = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    peak_mb = peak / (1024 * 1024)
    tracemalloc.stop()

    rl = out.get("rate_limit") or rate_limit_stats()
    sched = out.get("scheduler") or {}
    qva = out.get("validation_verdict") or {}
    nonempty = sum(1 for s in (out.get("summaries") or []) if (s or "").strip())

    prior = {
        "wall_clock_sec": 111.5,
        "chunks": 8,
        "peak_memory_mb": 33.2,
        "qva_confidence": 0.721,
        "note": "companion run from prior pass (before rate-limit backoff split)",
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "doc": str(pdf),
        "pages_note": "FinalReport.pdf (production document in repo root)",
        "raw_triage_blocks": len(raw),
        "chunks": len(chunks),
        "summaries_nonempty": nonempty,
        "wall_clock_sec": round(wall, 1),
        "peak_memory_mb": round(peak_mb, 1),
        "qva": {
            "passed": qva.get("passed"),
            "confidence": qva.get("confidence"),
            "faithfulness": qva.get("faithfulness"),
            "coverage": qva.get("coverage"),
        },
        "rate_limit": rl,
        "scheduler": sched,
        "hard_isolation_timeouts": rl.get("hard_isolation_timeouts"),
        "rate_limit_requeues": rl.get("rate_limit_requeues")
        or sched.get("rate_limit_requeues"),
        "avg_backoff_sec": rl.get("avg_backoff_sec")
        or sched.get("avg_rate_limit_backoff_sec"),
        "final_summary_len": len(str(out.get("final_summary") or "")),
        "final_summary_preview": str(out.get("final_summary") or "")[:700],
        "compile_meta": {
            k: (out.get("compile_meta") or {}).get(k)
            for k in ("engine", "compile_calls", "compile_carbon_g", "used_heavy", "escalation_count")
        },
        "live_nim": True,
        "stubbed": False,
        "prior_companion_run": prior,
        "chunk_count_delta_vs_prior": len(chunks) - int(prior["chunks"]),
        "chunk_count_note": (
            "Same FinalReport.pdf; chunk count may differ if triage/chunking "
            "settings changed (e.g. texts[:200] cap removal only affected large docs)."
            if len(chunks) != prior["chunks"]
            else "Chunk count matches prior companion run."
        ),
    }

    out_dir = ROOT / "eval_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "finalreport_rate_limit_fix.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "final_summary_preview"}, indent=2), flush=True)
    print(f"Wrote {out_path}", flush=True)

    # Additive landing-page bench row
    landing_src = out_dir / "sequential_vs_dag.json"
    fe = REPO / "frontend" / "data" / "sequential_vs_dag.json"
    if landing_src.exists() or fe.exists():
        src = landing_src if landing_src.exists() else fe
        data = json.loads(src.read_text(encoding="utf-8"))
        rows = list(data.get("rows") or [])
        # Remove prior FinalReport validation rows to avoid duplicates on re-run
        rows = [r for r in rows if r.get("label") != "FinalReport.pdf live validation"]
        rows.append(
            {
                "chunks": len(chunks),
                "sequential_wall_ms": None,
                "parallel_wall_ms": round(wall * 1000.0, 1),
                "speedup": None,
                "sequential_carbon_g": None,
                "parallel_carbon_g": float(
                    (out.get("carbon_spent_g") or 0.0)
                ),
                "provider": "nim",
                "label": "FinalReport.pdf live validation",
                "qva_confidence": qva.get("confidence"),
                "rate_limit_requeues": report["rate_limit_requeues"],
                "hard_isolation_timeouts": report["hard_isolation_timeouts"],
                "wall_clock_sec": report["wall_clock_sec"],
            }
        )
        data["rows"] = rows
        data["finalreport_validation"] = {
            "wall_clock_sec": report["wall_clock_sec"],
            "chunks": len(chunks),
            "qva_confidence": qva.get("confidence"),
            "rate_limit_requeues": report["rate_limit_requeues"],
            "hard_isolation_timeouts": report["hard_isolation_timeouts"],
            "generated_at": report["generated_at"],
        }
        data["note"] = (
            "Measured against live NIM. Includes FinalReport.pdf rate-limit-fix validation row."
        )
        landing_src.write_text(json.dumps(data, indent=2), encoding="utf-8")
        fe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(landing_src, fe)
        print(f"Updated landing bench → {fe}", flush=True)


if __name__ == "__main__":
    main()
