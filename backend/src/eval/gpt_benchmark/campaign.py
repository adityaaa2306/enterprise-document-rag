"""
Benchmark campaign orchestration.

Creates a versioned, append-only campaign directory, runs the existing
``run_benchmark`` protocol unchanged, then writes campaign metadata,
dashboard-ready JSON, a Markdown report, and an execution log.

Does not modify retrieval, prompt construction, or production APIs.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TextIO

from src.eval.gpt_benchmark.dashboard_export import build_dashboard_payload
from src.eval.gpt_benchmark.questions import SMOKE_DOCUMENT_FILENAME, questions_for_suite
from src.eval.gpt_benchmark.report import render_markdown_report
from src.eval.gpt_benchmark.store import DEFAULT_RESULTS_DIR
from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    DOCUMENT_FREEZE_VERSION,
    PROMPT_VERSION,
    RETRIEVAL_VERSION,
    SUMMARIZE_PROMPT_VERSION,
)
from src.eval.gpt_benchmark.workloads import (
    WORKLOAD_DOCUMENT_SUMMARIZATION,
    WORKLOAD_INTERACTIVE_RAG,
    is_summarization_suite,
    normalize_suite,
    workload_for_suite,
)

log = logging.getLogger(__name__)

CAMPAIGNS_ROOT = DEFAULT_RESULTS_DIR / "campaigns"


@dataclass
class CampaignPaths:
    campaign_id: str
    root: Path
    config: Path
    metadata: Path
    results: Path
    summary: Path
    dashboard: Path
    report: Path
    execution_log: Path


class _TeeStream:
    """Write to both the original stream and a log file."""

    def __init__(self, primary: TextIO, log_fh: TextIO):
        self._primary = primary
        self._log = log_fh

    def write(self, data: str) -> int:
        self._primary.write(data)
        self._log.write(data)
        self._log.flush()
        return len(data)

    def flush(self) -> None:
        self._primary.flush()
        self._log.flush()

    def fileno(self) -> int:
        return self._primary.fileno()

    def isatty(self) -> bool:
        return bool(getattr(self._primary, "isatty", lambda: False)())


def _unique_campaign_id(ts: str, label: Optional[str] = None) -> str:
    base = f"campaign_{ts}_v{BENCHMARK_VERSION}"
    if label:
        safe = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in label.strip())
        safe = safe.strip("-_")[:48]
        if safe:
            base = f"{base}_{safe}"
    return base


def create_campaign_dir(
    *,
    label: Optional[str] = None,
    campaigns_root: Optional[Path] = None,
) -> CampaignPaths:
    """
    Create a new campaign directory. Never overwrites an existing campaign.
    """
    root_base = Path(campaigns_root) if campaigns_root else CAMPAIGNS_ROOT
    root_base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    campaign_id = _unique_campaign_id(ts, label)
    root = root_base / campaign_id
    if root.exists():
        # Collision within the same UTC second — suffix until unique
        n = 2
        while True:
            candidate = root_base / f"{campaign_id}_{n}"
            if not candidate.exists():
                campaign_id = f"{campaign_id}_{n}"
                root = candidate
                break
            n += 1
    root.mkdir(parents=False, exist_ok=False)

    return CampaignPaths(
        campaign_id=campaign_id,
        root=root,
        config=root / "config.json",
        metadata=root / "metadata.json",
        results=root / "results.json",
        summary=root / "summary.json",
        dashboard=root / "dashboard.json",
        report=root / "REPORT.md",
        execution_log=root / "execution.log",
    )


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_config(
    *,
    campaign_id: str,
    document_id: Optional[str],
    filename: Optional[str],
    suite: str,
    models: Sequence[str],
    questions: Sequence[str],
    max_tokens: int,
    temperature: float,
    dry_run: bool,
    assemble_tier: str,
    workload: str = WORKLOAD_INTERACTIVE_RAG,
) -> Dict[str, Any]:
    if workload == WORKLOAD_DOCUMENT_SUMMARIZATION:
        return {
            "campaign_id": campaign_id,
            "benchmark_version": BENCHMARK_VERSION,
            "workload": workload,
            "document_freeze_version": DOCUMENT_FREEZE_VERSION,
            "prompt_version": SUMMARIZE_PROMPT_VERSION,
            "suite": suite,
            "document_id": document_id,
            "filename": filename,
            "models": list(models),
            "questions": list(questions),
            "question_count": len(questions),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "dry_run": dry_run,
            "protocol": {
                "freeze_document_once": True,
                "consistency_gate_before_each_model": True,
                "shared_frozen_prompt_across_models": True,
            },
        }
    return {
        "campaign_id": campaign_id,
        "benchmark_version": BENCHMARK_VERSION,
        "workload": workload,
        "retrieval_version": RETRIEVAL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "suite": suite,
        "document_id": document_id,
        "filename": filename,
        "models": list(models),
        "questions": list(questions),
        "question_count": len(questions),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "dry_run": dry_run,
        "assemble_tier": assemble_tier,
        "protocol": {
            "retrieve_once_per_question": True,
            "consistency_gate_before_each_model": True,
            "shared_frozen_prompt_across_models": True,
        },
    }


def _build_metadata(
    *,
    campaign_id: str,
    config: Dict[str, Any],
    results_payload: Dict[str, Any],
    paths: CampaignPaths,
) -> Dict[str, Any]:
    meta = results_payload.get("metadata") or {}
    summary = results_payload.get("summary") or {}
    questions_meta = []
    for q in results_payload.get("questions") or []:
        questions_meta.append(
            {
                "question": q.get("question"),
                "document_id": q.get("document_id") or meta.get("document_id"),
                "context_hash": q.get("context_hash"),
                "prompt_hash": q.get("prompt_hash"),
                "chunk_count": q.get("chunk_count"),
            }
        )
    return {
        "campaign_id": campaign_id,
        "benchmark_version": meta.get("benchmark_version") or BENCHMARK_VERSION,
        "workload": meta.get("workload")
        or config.get("workload")
        or WORKLOAD_INTERACTIVE_RAG,
        "retrieval_version": meta.get("retrieval_version") or config.get("retrieval_version"),
        "document_freeze_version": meta.get("document_freeze_version")
        or config.get("document_freeze_version"),
        "prompt_version": meta.get("prompt_version")
        or meta.get("prompt_template_version")
        or config.get("prompt_version")
        or PROMPT_VERSION,
        "document_id": meta.get("document_id") or config.get("document_id"),
        "timestamp_utc": meta.get("timestamp_utc") or meta.get("timestamp"),
        "finished_utc": meta.get("finished_utc"),
        "suite": meta.get("suite") or config.get("suite"),
        "models": meta.get("models") or config.get("models"),
        "dry_run": meta.get("dry_run"),
        "total_runtime_sec": summary.get("total_runtime_sec"),
        "total_api_cost_usd": summary.get("total_api_cost_usd")
        or summary.get("estimated_api_cost_usd"),
        "context_and_prompt_hashes": questions_meta,
        "artifacts": {
            "config": paths.config.name,
            "metadata": paths.metadata.name,
            "results": paths.results.name,
            "summary": paths.summary.name,
            "dashboard": paths.dashboard.name,
            "report": paths.report.name,
            "execution_log": paths.execution_log.name,
        },
        "campaign_root": str(paths.root),
    }


def run_campaign(
    *,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
    suite: str = "smoke",
    workload: Optional[str] = None,
    models: Optional[Sequence[str]] = None,
    questions: Optional[Sequence[str]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    dry_run: bool = False,
    assemble_tier: str = "heavy",
    label: Optional[str] = None,
    campaigns_root: Optional[Path] = None,
    dataset_path: Optional[str] = None,
    dataset_id: Optional[str] = None,
    quality_evaluator: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute one append-only benchmark campaign and persist publishable artifacts.
    """
    from src.eval.gpt_benchmark.participants import (
        DEFAULT_BENCHMARK_PARTICIPANTS,
        normalize_participants,
    )
    from src.eval.gpt_benchmark.runner import run_benchmark
    from src.eval.gpt_benchmark.summarize.runner import run_summarization_benchmark
    from src.eval.gpt_benchmark.summarize.prompts import SUMMARIZATION_TASK_LABEL
    from src.eval.gpt_benchmark.summarize.suites import suite_profile

    suite = normalize_suite(suite)
    resolved_workload = (workload or workload_for_suite(suite)).strip().lower()
    if is_summarization_suite(suite):
        resolved_workload = WORKLOAD_DOCUMENT_SUMMARIZATION

    model_list = normalize_participants(
        list(models) if models is not None else list(DEFAULT_BENCHMARK_PARTICIPANTS)
    )

    if resolved_workload == WORKLOAD_DOCUMENT_SUMMARIZATION:
        profile = suite_profile(suite)
        q_list = [SUMMARIZATION_TASK_LABEL]
        tok = int(max_tokens if max_tokens is not None else profile.max_tokens)
        temp = float(temperature if temperature is not None else profile.temperature)
        if not filename and not document_id and profile.suite_id == "summarization-smoke":
            filename = SMOKE_DOCUMENT_FILENAME
    else:
        q_list = list(questions) if questions is not None else questions_for_suite(suite)
        tok = int(max_tokens if max_tokens is not None else 500)
        temp = float(temperature if temperature is not None else 0.2)
        if not filename and not document_id and suite == "smoke":
            filename = SMOKE_DOCUMENT_FILENAME

    paths = create_campaign_dir(label=label, campaigns_root=campaigns_root)
    config = _build_config(
        campaign_id=paths.campaign_id,
        document_id=document_id,
        filename=filename,
        suite=suite,
        models=model_list,
        questions=q_list,
        max_tokens=tok,
        temperature=temp,
        dry_run=dry_run,
        assemble_tier=assemble_tier,
        workload=resolved_workload,
    )
    config["quality_evaluator"] = quality_evaluator
    config["dataset_path"] = dataset_path
    config["dataset_id"] = dataset_id
    _write_json(paths.config, config)

    # Tee stdout + logging into execution.log (never truncate other campaigns)
    log_fh = paths.execution_log.open("w", encoding="utf-8")
    log_fh.write(
        f"# Execution log for {paths.campaign_id}\n"
        f"# started_utc={datetime.now(timezone.utc).isoformat()}\n\n"
    )
    log_fh.flush()

    handler = logging.StreamHandler(log_fh)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = _TeeStream(old_stdout, log_fh)  # type: ignore[assignment]
    sys.stderr = _TeeStream(old_stderr, log_fh)  # type: ignore[assignment]

    results_payload: Dict[str, Any] = {}
    try:
        print(f"Campaign: {paths.campaign_id}")
        print(f"Directory: {paths.root}")
        print()

        if resolved_workload == WORKLOAD_DOCUMENT_SUMMARIZATION:
            results_payload = run_summarization_benchmark(
                document_id=document_id,
                filename=filename,
                suite=suite,
                models=model_list,
                max_tokens=tok,
                temperature=temp,
                dry_run=dry_run,
                out_dir=paths.root,
                dataset_path=dataset_path,
                dataset_id=dataset_id,
                quality_evaluator=quality_evaluator,
            )
        else:
            results_payload = run_benchmark(
                document_id=document_id,
                filename=filename,
                suite=suite,
                models=model_list,
                questions=q_list,
                max_tokens=tok,
                temperature=temp,
                dry_run=dry_run,
                out_dir=paths.root,
                assemble_tier=assemble_tier,
                dataset_path=dataset_path,
                dataset_id=dataset_id,
                quality_evaluator=quality_evaluator,
            )

        # Canonical campaign filenames (keep runner timestamped files too)
        runner_results = Path(
            (results_payload.get("metadata") or {}).get("results_path") or ""
        )
        runner_summary = Path(
            (results_payload.get("metadata") or {}).get("summary_path") or ""
        )
        if runner_results.is_file():
            paths.results.write_text(
                runner_results.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            _write_json(paths.results, results_payload)

        aggregates = results_payload.get("aggregates") or {}
        if runner_summary.is_file():
            paths.summary.write_text(
                runner_summary.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            _write_json(paths.summary, aggregates)

        # Prefer reading aggregates from summary file for dashboard
        if paths.summary.is_file():
            aggregates = json.loads(paths.summary.read_text(encoding="utf-8"))

        # Ensure results.json carries latest metadata paths for this campaign
        results_payload.setdefault("metadata", {})
        results_payload["metadata"]["campaign_id"] = paths.campaign_id
        results_payload["metadata"]["campaign_root"] = str(paths.root)
        results_payload["metadata"]["results_path"] = str(paths.results)
        results_payload["metadata"]["summary_path"] = str(paths.summary)
        _write_json(paths.results, results_payload)

        dashboard = build_dashboard_payload(
            campaign_id=paths.campaign_id,
            results_payload=results_payload,
            aggregates=aggregates,
        )
        _write_json(paths.dashboard, dashboard)

        report_md = render_markdown_report(
            campaign_id=paths.campaign_id,
            config=config,
            results_payload=results_payload,
            aggregates=aggregates,
            dashboard=dashboard,
        )
        paths.report.write_text(report_md, encoding="utf-8")

        # Fill resolved document_id into config after run
        config["document_id"] = (results_payload.get("metadata") or {}).get(
            "document_id"
        ) or document_id
        _write_json(paths.config, config)

        metadata = _build_metadata(
            campaign_id=paths.campaign_id,
            config=config,
            results_payload=results_payload,
            paths=paths,
        )
        _write_json(paths.metadata, metadata)

        print()
        print("=== CAMPAIGN ARTIFACTS ===")
        print(f"config:         {paths.config}")
        print(f"metadata:       {paths.metadata}")
        print(f"results:        {paths.results}")
        print(f"summary:        {paths.summary}")
        print(f"dashboard:      {paths.dashboard}")
        print(f"report:         {paths.report}")
        print(f"execution_log:  {paths.execution_log}")

        return {
            "campaign_id": paths.campaign_id,
            "campaign_root": str(paths.root),
            "paths": {
                "config": str(paths.config),
                "metadata": str(paths.metadata),
                "results": str(paths.results),
                "summary": str(paths.summary),
                "dashboard": str(paths.dashboard),
                "report": str(paths.report),
                "execution_log": str(paths.execution_log),
            },
            "results": results_payload,
            "aggregates": aggregates,
            "dashboard": dashboard,
            "metadata": metadata,
            "config": config,
        }
    except Exception:
        log_fh.write("\n# ERROR\n")
        log_fh.write(traceback.format_exc())
        log_fh.flush()
        raise
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        root_logger.removeHandler(handler)
        log_fh.write(
            f"\n# finished_utc={datetime.now(timezone.utc).isoformat()}\n"
        )
        log_fh.close()
