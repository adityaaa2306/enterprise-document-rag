#!/usr/bin/env python3
"""
Offline GPT benchmark campaign entrypoint (developer-only).

Isolated from production Interactive RAG. Does not run during normal app usage.

Writes a versioned folder under benchmark_results/campaigns/ containing:
  config.json, metadata.json, results.json, summary.json,
  dashboard.json, REPORT.md, execution.log

Examples:
  # Interactive RAG — safe credit check (retrieval only, no OpenAI spend)
  python run_benchmark.py --suite smoke --dry-run --label attendance-smoke

  # Interactive RAG smoke on Student Attendance App.pdf
  python run_benchmark.py --suite smoke --filename "Student Attendance App.pdf"

  # Document Summarization smoke (freeze chunks + summarize)
  python run_benchmark.py --suite summarization-smoke --dry-run --label sum-smoke

  python run_benchmark.py --suite summarization-standard --filename "Student Attendance App.pdf"

  # Explicit document id
  python run_benchmark.py --suite smoke --document-id <uuid>

  # Tiny spend check (1 question × selected models)
  python run_benchmark.py --suite smoke --limit 1 --models gpt-5-nano
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))

from src.eval.gpt_benchmark.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
