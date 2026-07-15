"""
Generate a synthetic ~1200-page PDF and run the full pipeline against live NIM.

Usage:
  cd backend
  python scripts/run_large_doc_live_nim.py --pages 1200
  python scripts/run_large_doc_live_nim.py --pages 1200 --max-chunks 48
"""
from __future__ import annotations

import argparse
import json
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


def _write_pdf(path: Path, pages: int) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        y = 750
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Page {i+1} of {pages} — Green Agentic RAG scale proof")
        y -= 20
        for line in range(45):
            c.drawString(
                50,
                y,
                (
                    f"Ch{i // 40 + 1}.{i % 40} L{line}: carbon-aware hierarchical RAG, "
                    f"QVA gates, CRE floors, live NIM latency variance sample {i}-{line}."
                )[:95],
            )
            y -= 15
        c.showPage()
        if (i + 1) % 100 == 0:
            print(f"  wrote {i+1}/{pages} pages...", flush=True)
    c.save()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1200)
    ap.add_argument("--pdf", type=str, default="")
    ap.add_argument("--max-chunks", type=int, default=0, help="0 = no extra cap")
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    pdf_path = (
        Path(args.pdf)
        if args.pdf
        else (REPO / "eval_docs" / f"scale_{args.pages}p.pdf")
    )
    if not pdf_path.exists():
        print(f"Generating {args.pages}-page PDF at {pdf_path} ...", flush=True)
        _write_pdf(pdf_path, args.pages)

    from src.core.config import settings
    from src.agents import triage, models
    from src.chunking import ChunkingService
    from src.core.pipeline_executor import execute_document_dag

    assert (settings.NVIDIA_API_KEY or "").strip(), "NVIDIA_API_KEY required"

    models.load_nim_client()
    tracemalloc.start()
    t0 = time.perf_counter()
    peak_mb = 0.0

    print("Triaging PDF...", flush=True)
    raw = triage.triage_document(str(pdf_path), "pdf", settings.TRIAGE_STRATEGY)
    print(f"Triage returned {len(raw)} raw blocks", flush=True)
    chunks, _parents, meta = ChunkingService().build(raw, document_id=f"scale-{args.pages}p")
    print(f"Adaptive chunks={len(chunks)} meta={meta}", flush=True)
    if args.max_chunks and len(chunks) > args.max_chunks:
        chunks = chunks[: args.max_chunks]
        print(f"Capped to {len(chunks)} chunks for this run", flush=True)

    state: Dict[str, Any] = {
        "job_id": f"live-scale-{args.pages}p",
        "chunks": chunks,
        "total_chunks": len(chunks),
        "chunk_routing": [
            {"chunk_index": i, "tier": "medium"} for i in range(len(chunks))
        ],
        "routing_decision": {
            "tier": "medium",
            "selected_model": settings.medium_models()[0],
            "fallbacks": list(settings.medium_models()),
        },
        "features": {"grid_intensity": float(settings.LOCAL_GRID_INTENSITY)},
        "pipeline_intelligence": {
            "strategy": {
                "hierarchy_fan_in": 8,
                "hierarchy_max_depth": 12,
                "skip_regional_below": 0,
                "qva_confidence_threshold": 0.55,
                "qva_compile_threshold": 0.50,
                "max_escalations": 1,
                "max_escalate_chunks": 8,
                "medium_first": True,
            }
        },
        "carbon_spent_g": 0.0,
        "agent_telemetry": [],
    }

    progress_log = []

    def pcb(pct, msg, extra):
        nonlocal peak_mb
        _cur, peak = tracemalloc.get_traced_memory()
        peak_mb = max(peak_mb, peak / (1024 * 1024))
        progress_log.append(
            {
                "t": round(time.perf_counter() - t0, 1),
                "pct": pct,
                "msg": msg,
                "dag": (extra or {}).get("dag"),
            }
        )
        print(f"[{progress_log[-1]['t']:7.1f}s] {pct:5.1f}% {msg}", flush=True)

    print(f"Starting live NIM DAG on {len(chunks)} chunks...", flush=True)
    out = execute_document_dag(state, progress_cb=pcb)
    wall = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    peak_mb = max(peak_mb, peak / (1024 * 1024))
    tracemalloc.stop()

    cancels = [
        t
        for t in (out.get("agent_telemetry") or [])
        if (not t.get("success", True))
        or "timeout" in str(t.get("error", "")).lower()
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages_requested": args.pages,
        "pdf": str(pdf_path),
        "chunks": len(chunks),
        "wall_clock_sec": round(wall, 1),
        "peak_memory_mb": round(peak_mb, 1),
        "final_summary_len": len(str(out.get("final_summary") or "")),
        "final_summary_preview": str(out.get("final_summary") or "")[:800],
        "qva": out.get("validation_verdict"),
        "compile_meta": {
            k: (out.get("compile_meta") or {}).get(k)
            for k in (
                "engine",
                "compile_calls",
                "compile_carbon_g",
                "used_heavy",
                "escalation_count",
                "perf_metrics",
            )
        },
        "nodes_with_errors_or_timeouts": len(cancels),
        "progress_ticks": len(progress_log),
        "live_nim": True,
        "stubbed": False,
    }
    out_path = (
        Path(args.out)
        if args.out
        else (ROOT / "eval_out" / f"live_scale_{args.pages}p.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "final_summary_preview"}, indent=2), flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
