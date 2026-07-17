"""
Developer CLI for offline GPT benchmarking / campaigns.

Usage (from repo root) — recommended campaign workflow:
  python run_benchmark.py --suite smoke --filename "Student Attendance App.pdf"

  # Document summarization
  python run_benchmark.py --suite summarization-smoke --dry-run --label sum-smoke

Dry-run campaign (no OpenAI spend):
  python run_benchmark.py --suite smoke --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional


def _ensure_backend_on_path() -> None:
    backend = Path(__file__).resolve().parents[3]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Offline benchmark campaign (isolated from production Interactive RAG / "
            "summarization). Freezes inputs once, runs participants sequentially, and "
            "writes a versioned campaign folder with dashboard JSON and a Markdown report."
        )
    )
    p.add_argument(
        "--workload",
        choices=("interactive_rag", "document_summarization", "auto"),
        default="auto",
        help=(
            "Benchmark workload. 'auto' infers from --suite "
            "(summarization-* → document_summarization)."
        ),
    )
    p.add_argument(
        "--suite",
        default="smoke",
        help=(
            "RAG: smoke | full. "
            "Summarization: summarization-smoke | summarization-standard | "
            "summarization-large."
        ),
    )
    p.add_argument(
        "--document-id",
        default=None,
        help="Canonical document_id / job_id of an already-ingested document",
    )
    p.add_argument(
        "--filename",
        default=None,
        help='Look up document by job filename (default smoke: "Student Attendance App.pdf")',
    )
    p.add_argument(
        "--models",
        default="intelligent-router,gpt-5-nano,gpt-5-mini,gpt-5.5",
        help=(
            "Comma-separated participants. Include 'intelligent-router' for the "
            "project's Intelligent Routing System (in-process NIM), plus OpenAI "
            "model ids (e.g. gpt-5-nano,gpt-5-mini,gpt-5.5)."
        ),
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Override suite default max completion tokens",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Override suite default temperature",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Freeze inputs and estimate cost only — no generation spend",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on number of questions (RAG only)",
    )
    p.add_argument(
        "--label",
        default=None,
        help="Optional campaign label suffix (e.g. attendance-smoke, summarization-smoke)",
    )
    p.add_argument(
        "--dataset",
        default=None,
        help="Optional path to reference JSON dataset for quality scoring",
    )
    p.add_argument(
        "--dataset-id",
        default=None,
        help="Optional dataset id under gpt_benchmark datasets/",
    )
    p.add_argument(
        "--quality-evaluator",
        default=None,
        help="Quality evaluator id (default: default_composite_v1)",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="Override output directory (flat mode) or campaigns root parent",
    )
    p.add_argument(
        "--flat",
        action="store_true",
        help="Write timestamped results without campaign packaging",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_backend_on_path()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from src.eval.gpt_benchmark.consistency import BenchmarkConsistencyError
    from src.eval.gpt_benchmark.questions import questions_for_suite
    from src.eval.gpt_benchmark.workloads import (
        WORKLOAD_DOCUMENT_SUMMARIZATION,
        is_summarization_suite,
        normalize_suite,
        workload_for_suite,
    )

    suite = normalize_suite(args.suite)
    workload = args.workload
    if workload == "auto":
        workload = workload_for_suite(suite)

    models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    questions = None
    if workload != WORKLOAD_DOCUMENT_SUMMARIZATION and not is_summarization_suite(suite):
        questions = questions_for_suite(suite)
        if args.limit is not None:
            questions = questions[: max(0, int(args.limit))]

    try:
        if args.flat:
            if workload == WORKLOAD_DOCUMENT_SUMMARIZATION or is_summarization_suite(
                suite
            ):
                from src.eval.gpt_benchmark.summarize.runner import (
                    run_summarization_benchmark,
                )

                payload = run_summarization_benchmark(
                    document_id=args.document_id,
                    filename=args.filename,
                    suite=suite,
                    models=models,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    dry_run=bool(args.dry_run),
                    out_dir=Path(args.out_dir) if args.out_dir else None,
                    dataset_path=args.dataset,
                    dataset_id=args.dataset_id,
                    quality_evaluator=args.quality_evaluator,
                )
            else:
                from src.eval.gpt_benchmark.runner import run_benchmark

                payload = run_benchmark(
                    document_id=args.document_id,
                    filename=args.filename,
                    suite=suite,
                    models=models,
                    questions=questions,
                    max_tokens=int(args.max_tokens if args.max_tokens is not None else 500),
                    temperature=float(
                        args.temperature if args.temperature is not None else 0.2
                    ),
                    dry_run=bool(args.dry_run),
                    out_dir=Path(args.out_dir) if args.out_dir else None,
                    dataset_path=args.dataset,
                    dataset_id=args.dataset_id,
                    quality_evaluator=args.quality_evaluator,
                )
            summary = payload.get("summary") or {}
            aggregates = payload.get("aggregates") or {}
            meta = payload.get("metadata") or {}
            print("\n=== PER-MODEL AGGREGATES ===")
            print(json.dumps(aggregates.get("per_model") or {}, indent=2))
            print("\n=== TOTALS ===")
            print(json.dumps(summary, indent=2))
            print(f"\nResults: {meta.get('results_path')}")
            print(f"Summary: {meta.get('summary_path')}")
        else:
            from src.eval.gpt_benchmark.campaign import run_campaign

            campaigns_root = None
            if args.out_dir:
                campaigns_root = Path(args.out_dir) / "campaigns"

            outcome = run_campaign(
                document_id=args.document_id,
                filename=args.filename,
                suite=suite,
                workload=workload,
                models=models,
                questions=questions,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                dry_run=bool(args.dry_run),
                label=args.label,
                campaigns_root=campaigns_root,
                dataset_path=args.dataset,
                dataset_id=args.dataset_id,
                quality_evaluator=args.quality_evaluator,
            )
            print("\n=== CAMPAIGN COMPLETE ===")
            print(f"Campaign ID: {outcome['campaign_id']}")
            print(f"Root:        {outcome['campaign_root']}")
            print(f"Report:      {outcome['paths']['report']}")
            print(f"Dashboard:   {outcome['paths']['dashboard']}")
            print(
                "\nTotals:",
                json.dumps(
                    (outcome.get("results") or {}).get("summary") or {}, indent=2
                ),
            )
    except BenchmarkConsistencyError as e:
        print(f"CONSISTENCY ERROR: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            "\nDry-run complete. Review campaign cost upper-bounds, then re-run "
            "without --dry-run to spend credits."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
