"""
Live FinalReport re-run to verify chain time-slices (map + compile).
Logs CHAIN_SLICE lines and writes before/after style report JSON.
"""
from __future__ import annotations

import json
import logging
import time
import tracemalloc
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("validate_chain_slices")

# Capture CHAIN_SLICE log lines
_SLICE_LINES: list[str] = []


class _SliceHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "CHAIN_SLICE" in msg:
            _SLICE_LINES.append(msg)


def main() -> None:
    from src.agents import models, triage
    from src.chunking import ChunkingService
    from src.core.config import settings
    from src.core.pipeline_executor import execute_document_dag

    h = _SliceHandler()
    logging.getLogger().addHandler(h)
    logging.getLogger("src.agents.models").addHandler(h)
    logging.getLogger("src.core.chain_time_budget").addHandler(h)

    pdf = Path(__file__).resolve().parents[2] / "FinalReport.pdf"
    assert pdf.exists(), pdf

    models.load_nim_client()
    tracemalloc.start()
    t0 = time.perf_counter()
    raw = triage.triage_document(str(pdf), "pdf", settings.TRIAGE_STRATEGY)
    chunks, _, meta = ChunkingService().build(raw, document_id="finalreport-slices")
    log.info("chunks=%s", len(chunks))

    state = {
        "job_id": "live-chain-slices",
        "chunks": chunks,
        "total_chunks": len(chunks),
        "chunk_routing": [{"chunk_index": i, "tier": "light"} for i in range(len(chunks))],
        # Force medium on some chunks to exercise map chain slices
        "routing_decision": {
            "tier": "medium",
            "fallbacks": list(settings.medium_models()),
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
    }
    # Alternate tiers so medium chain is exercised
    for i in range(len(chunks)):
        state["chunk_routing"][i]["tier"] = "medium" if i % 2 else "light"

    def pcb(pct, msg, extra):
        print(f"[{time.perf_counter()-t0:6.1f}s] {pct:5.1f}% {msg}", flush=True)

    # Generous but finite DAG wall (not a substitute for slice fix)
    deadline = time.monotonic() + 600.0
    out = execute_document_dag(state, progress_cb=pcb, deadline_mono=deadline)
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    final = str(out.get("final_summary") or "")
    stitched = "stitched fallback" in final.lower()
    unable = "Unable to generate a final summary" in final

    # Parse slice lines for report
    slice_events = list(_SLICE_LINES)
    report = {
        "doc": str(pdf),
        "chunks": len(chunks),
        "wall_clock_sec": round(wall, 1),
        "peak_memory_mb": round(peak / 1024 / 1024, 1),
        "final_summary_len": len(final),
        "final_summary_preview": final[:700],
        "used_stitched_fallback": stitched,
        "unable_empty": unable,
        "chain_slice_enabled": bool(getattr(settings, "CHAIN_SLICE_ENABLED", True)),
        "compile_hedged": bool(getattr(settings, "COMPILE_HEDGED_FALLBACK_ENABLED", False)),
        "map_fractions": getattr(settings, "MAP_CHAIN_SLICE_FRACTIONS", ""),
        "compile_fractions": getattr(settings, "COMPILE_CHAIN_SLICE_FRACTIONS", ""),
        "chain_slice_log_lines": slice_events,
        "fallback_invoked_in_logs": any(
            "falling through" in L or "hedged_compile" in L or "outcome=success" in L
            for L in slice_events
        ),
        "primary_timeout_slice_seen": any("timeout_slice" in L for L in slice_events),
        "qva": out.get("validation_verdict"),
        "compile_meta_keys": list((out.get("compile_meta") or {}).keys()),
    }
    out_path = Path("eval_out/finalreport_chain_slices.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "final_summary_preview"}, indent=2))
    print("--- preview ---")
    print(final[:500])


if __name__ == "__main__":
    main()
