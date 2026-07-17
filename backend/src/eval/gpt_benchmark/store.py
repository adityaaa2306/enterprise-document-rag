"""Persist structured benchmark runs and auto-generated summaries."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.eval.gpt_benchmark.summary import aggregate_per_model

# Repo root: .../green-agentic-rag-main
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RESULTS_DIR = REPO_ROOT / "benchmark_results"


def results_dir(explicit: Optional[Path] = None) -> Path:
    path = Path(explicit) if explicit else DEFAULT_RESULTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run(
    payload: Dict[str, Any],
    *,
    out_dir: Optional[Path] = None,
    filename: Optional[str] = None,
) -> Path:
    directory = results_dir(out_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = filename or f"gpt_benchmark_{ts}.json"
    if not name.endswith(".json"):
        name = f"{name}.json"
    path = directory / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_summary(
    summary_payload: Dict[str, Any],
    *,
    results_path: Path,
) -> Path:
    """Write ``*_summary.json`` next to the full results file."""
    stem = results_path.stem
    if stem.endswith("_summary"):
        path = results_path
    else:
        path = results_path.with_name(f"{stem}_summary.json")
    path.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def write_run_with_summary(
    payload: Dict[str, Any],
    *,
    out_dir: Optional[Path] = None,
    filename: Optional[str] = None,
) -> Tuple[Path, Path, Dict[str, Any]]:
    """
    Persist full results, generate aggregates, persist summary companion file.
    Returns (results_path, summary_path, aggregates).
    """
    results_path = write_run(payload, out_dir=out_dir, filename=filename)
    payload.setdefault("metadata", {})["results_path"] = str(results_path)

    aggregates = aggregate_per_model(payload)
    aggregates.setdefault("metadata", {})["results_path"] = str(results_path)
    summary_path = write_summary(aggregates, results_path=results_path)
    aggregates.setdefault("metadata", {})["summary_path"] = str(summary_path)
    aggregates.setdefault("totals", {})["summary_path"] = str(summary_path)
    aggregates.setdefault("totals", {})["results_path"] = str(results_path)

    # Rewrite summary with paths filled in
    summary_path.write_text(
        json.dumps(aggregates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    payload["aggregates"] = aggregates
    payload["metadata"]["summary_path"] = str(summary_path)
    results_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return results_path, summary_path, aggregates
