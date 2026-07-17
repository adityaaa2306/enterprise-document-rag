"""
Document Summarization benchmark runner.

Freezes document chunks + prompt once, then runs Intelligent Router + GPT
participants under identical conditions. Isolated from production HTTP /
document-processing pipelines.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.eval.gpt_benchmark.consistency import (
    BenchmarkConsistencyError,
    assert_identical_model_inputs,
)
from src.eval.gpt_benchmark.freeze import resolve_document_id
from src.eval.gpt_benchmark.openai_client import get_openai_client, run_model_streaming
from src.eval.gpt_benchmark.participants import (
    DEFAULT_BENCHMARK_PARTICIPANTS,
    describe_participants,
    display_name,
    is_system_participant,
    normalize_participants,
    participant_kind,
)
from src.eval.gpt_benchmark.pricing import estimate_api_cost_usd
from src.eval.gpt_benchmark.quality.attach import evaluate_run_quality
from src.eval.gpt_benchmark.quality.registry import DEFAULT_EVALUATOR_ID
from src.eval.gpt_benchmark.questions import SMOKE_DOCUMENT_FILENAME
from src.eval.gpt_benchmark.store import write_run_with_summary
from src.eval.gpt_benchmark.summarize.consistency import verify_frozen_summarization
from src.eval.gpt_benchmark.summarize.dataset import (
    extract_reference_summary,
    reference_for_document,
    resolve_summarization_dataset,
)
from src.eval.gpt_benchmark.summarize.freeze import (
    freeze_document_for_summarization,
    frozen_summarization_fingerprint,
)
from src.eval.gpt_benchmark.summarize.prompts import (
    SUMMARIZATION_TASK_LABEL,
    prompt_metadata,
)
from src.eval.gpt_benchmark.summarize.suites import suite_profile
from src.eval.gpt_benchmark.summary import aggregate_per_model
from src.eval.gpt_benchmark.system_runner import run_intelligent_router
from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    DOCUMENT_FREEZE_VERSION,
    SUMMARIZE_PROMPT_VERSION,
)
from src.eval.gpt_benchmark.workloads import WORKLOAD_DOCUMENT_SUMMARIZATION


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def _summary_length(text: str) -> Dict[str, int]:
    t = text or ""
    words = [w for w in t.split() if w]
    return {
        "summary_chars": len(t),
        "summary_words": len(words),
        "summary_length": len(t),
    }


def _attach_quality_and_length(
    row: Dict[str, Any],
    *,
    reference_summary: Optional[str],
    document_text: str,
    evaluator_id: str,
    dry_run: bool,
) -> None:
    quality = evaluate_run_quality(
        question=SUMMARIZATION_TASK_LABEL,
        reference_answer=reference_summary,
        candidate_answer=row.get("answer") or "",
        context=document_text,
        evaluator_id=evaluator_id,
        dry_run=dry_run,
    )
    row["quality"] = quality
    for key in (
        "quality_score",
        "correctness",
        "completeness",
        "groundedness",
        "conciseness",
    ):
        row[key] = quality.get(key)
    lengths = _summary_length(row.get("answer") or "")
    row.update(lengths)
    # Alias for explorer UI
    row["summary"] = row.get("answer") or ""


def run_summarization_benchmark(
    *,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
    suite: str = "summarization-smoke",
    models: Optional[Sequence[str]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    dry_run: bool = False,
    out_dir: Optional[Path] = None,
    dataset_path: Optional[str] = None,
    dataset_id: Optional[str] = None,
    quality_evaluator: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute one document summarization benchmark and write results + summary.
    """
    profile = suite_profile(suite)
    doc_id = resolve_document_id(
        document_id=document_id,
        filename=filename
        or (
            SMOKE_DOCUMENT_FILENAME
            if profile.suite_id == "summarization-smoke"
            else None
        ),
    )
    model_list = normalize_participants(
        list(models) if models is not None else list(DEFAULT_BENCHMARK_PARTICIPANTS)
    )
    tok_budget = int(max_tokens if max_tokens is not None else profile.max_tokens)
    temp = float(temperature if temperature is not None else profile.temperature)
    needs_openai = any(not is_system_participant(m) for m in model_list)
    needs_system = any(is_system_participant(m) for m in model_list)
    evaluator_id = (quality_evaluator or DEFAULT_EVALUATOR_ID).strip()
    dataset = resolve_summarization_dataset(
        suite=profile.suite_id, dataset_path=dataset_path, dataset_id=dataset_id
    )

    client = None
    if not dry_run and needs_openai:
        client = get_openai_client()

    started_dt = datetime.now(timezone.utc)
    started = started_dt.isoformat()
    wall_t0 = time.perf_counter()

    _print(
        f"Summarization benchmark v{BENCHMARK_VERSION} — suite={profile.suite_id} "
        f"participants={[display_name(m) for m in model_list]}"
    )
    _print(f"document_id={doc_id}  dry_run={dry_run}")
    _print(f"quality_evaluator={evaluator_id}  reference_items={len(dataset)}")
    if needs_system:
        _print(
            "Intelligent Router: in-process NIM + stored RoutingDecision "
            "(no production HTTP)."
        )
    _print()

    frozen = freeze_document_for_summarization(
        document_id=doc_id,
        suite=profile.suite_id,
        filename=filename,
    )
    identity = verify_frozen_summarization(frozen)
    input_fp = frozen_summarization_fingerprint(frozen)
    _print("Document frozen ✓")
    _print(f"  context_hash={frozen.context_hash}")
    _print(f"  prompt_hash={frozen.prompt_hash}")
    _print(
        f"  chunks={frozen.chunk_count}/{frozen.total_chunks_available}  "
        f"chars={frozen.document_chars}"
    )

    ref_item = reference_for_document(
        document_id=doc_id, filename=filename or frozen.filename, dataset=dataset
    )
    reference_summary = extract_reference_summary(ref_item)
    if reference_summary:
        _print("  reference_summary ✓")
    else:
        _print("  reference_summary — (quality will be skipped)")

    _print("Running:")
    for m in model_list:
        _print(f"  • {display_name(m)} ({participant_kind(m)})")

    shared_messages = frozen.messages
    model_runs: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    hits = frozen.chunk_count

    for model in model_list:
        verification = assert_identical_model_inputs(
            expected=identity,
            document_id=doc_id,
            messages=shared_messages,
            context_text=frozen.document_text,
            chunk_count=frozen.chunk_count,
            model=model,
            prompt_version=SUMMARIZE_PROMPT_VERSION,
        )
        if shared_messages is not frozen.messages:
            raise BenchmarkConsistencyError(
                f"Aborting before participant={model!r}: messages list was replaced"
            )

        if is_system_participant(model):
            run = run_intelligent_router(
                document_id=doc_id,
                question=SUMMARIZATION_TASK_LABEL,
                messages=shared_messages,
                context_tokens=frozen.context_tokens,
                retrieval_hits=hits,
                max_tokens=tok_budget,
                temperature=temp,
                input_verification=verification,
                dry_run=dry_run,
            )
            # Tag summarization execution path without mutating production router
            if isinstance(run.routing, dict):
                run.routing = {
                    **run.routing,
                    "workload": WORKLOAD_DOCUMENT_SUMMARIZATION,
                    "execution_path": "in_process_nim_summarization_via_routing_decision",
                }
            row = run.to_dict()
            _attach_quality_and_length(
                row,
                reference_summary=reference_summary,
                document_text=frozen.document_text,
                evaluator_id=evaluator_id,
                dry_run=dry_run,
            )
            model_runs.append(row)
            label = display_name(model)
            if dry_run and run.ok:
                ub = (run.provider_metadata or {}).get(
                    "estimated_api_cost_usd_upper_bound"
                ) or 0.0
                total_cost += float(ub)
                total_prompt_tokens += run.prompt_tokens
                _print(
                    f"    ✓ {label} (dry-run) prompt≈{run.prompt_tokens} tok "
                    f"route→{run.model_returned or '—'}"
                )
            elif run.ok:
                total_cost += run.estimated_api_cost_usd
                total_prompt_tokens += run.prompt_tokens
                total_completion_tokens += run.completion_tokens
                qscore = (row.get("quality") or {}).get("quality_score")
                qtxt = f"  q={qscore:.1f}" if isinstance(qscore, (int, float)) else ""
                _print(
                    f"    ✓ {label}  lat={run.latency_ms:.0f}ms  "
                    f"tok={run.total_tokens}  "
                    f"${run.estimated_api_cost_usd:.6f}  "
                    f"len={row.get('summary_length')}{qtxt}"
                )
            else:
                _print(f"    ✗ {label}  error={run.error}")
            continue

        if dry_run:
            prompt_blob = "\n".join(m.get("content") or "" for m in shared_messages)
            est_prompt = max(0, len(prompt_blob) // 4)
            est_cost = estimate_api_cost_usd(model, est_prompt, tok_budget)
            row = {
                "model": model,
                "model_requested": model,
                "model_returned": None,
                "ok": True,
                "dry_run": True,
                "participant_kind": "openai",
                "finish_reason": None,
                "prompt_tokens": est_prompt,
                "completion_tokens": 0,
                "completion_tokens_budget": tok_budget,
                "total_tokens": est_prompt,
                "latency_ms": None,
                "ttft_ms": None,
                "tokens_per_sec": None,
                "estimated_api_cost_usd": 0.0,
                "estimated_api_cost_usd_upper_bound": round(est_cost, 8),
                "input_verification": verification,
                "routing": {},
                "answer": "",
                "summary": "",
                "note": (
                    "Dry-run: no OpenAI call. Cost upper-bound assumes "
                    f"full max_tokens={tok_budget} completion."
                ),
            }
            _attach_quality_and_length(
                row,
                reference_summary=reference_summary,
                document_text=frozen.document_text,
                evaluator_id=evaluator_id,
                dry_run=True,
            )
            model_runs.append(row)
            total_cost += est_cost
            total_prompt_tokens += est_prompt
            _print(f"    ✓ {model} (dry-run) prompt≈{est_prompt} tok")
            continue

        assert client is not None
        run = run_model_streaming(
            client=client,
            model=model,
            messages=shared_messages,
            query=SUMMARIZATION_TASK_LABEL,
            context_tokens=frozen.context_tokens,
            retrieval_hits=hits,
            max_tokens=tok_budget,
            temperature=temp,
            input_verification=verification,
        )
        row = run.to_dict()
        _attach_quality_and_length(
            row,
            reference_summary=reference_summary,
            document_text=frozen.document_text,
            evaluator_id=evaluator_id,
            dry_run=False,
        )
        model_runs.append(row)
        if run.ok:
            total_cost += run.estimated_api_cost_usd
            total_prompt_tokens += run.prompt_tokens
            total_completion_tokens += run.completion_tokens
            qscore = (row.get("quality") or {}).get("quality_score")
            qtxt = f"  q={qscore:.1f}" if isinstance(qscore, (int, float)) else ""
            _print(
                f"    ✓ {model}  lat={run.latency_ms:.0f}ms  "
                f"tok={run.total_tokens}  "
                f"${run.estimated_api_cost_usd:.6f}  "
                f"len={row.get('summary_length')}{qtxt}"
            )
        else:
            _print(f"    ✗ {model}  error={run.error}")

    for row in model_runs:
        ver = row.get("input_verification") or {}
        if not ver.get("verified"):
            continue
        if ver.get("context_hash") != frozen.context_hash:
            raise BenchmarkConsistencyError(
                "Stored summarization run context_hash diverged from freeze"
            )
        if ver.get("prompt_hash") != frozen.prompt_hash:
            raise BenchmarkConsistencyError(
                "Stored summarization run prompt_hash diverged from freeze"
            )

    wall_sec = time.perf_counter() - wall_t0
    finished = datetime.now(timezone.utc).isoformat()

    # Artifact shape stays compatible with RAG campaigns: one "question" row.
    question_row = {
        "question": SUMMARIZATION_TASK_LABEL,
        "task": "document_summarization",
        "ok": True,
        "document_id": doc_id,
        "context_hash": frozen.context_hash,
        "prompt_hash": frozen.prompt_hash,
        "input_fingerprint": input_fp,
        "context_tokens": frozen.context_tokens,
        "chunk_count": frozen.chunk_count,
        "chunk_boundaries": frozen.chunk_boundaries,
        "total_chunks_available": frozen.total_chunks_available,
        "document_chars": frozen.document_chars,
        "document_freeze_version": DOCUMENT_FREEZE_VERSION,
        "prompt_version": SUMMARIZE_PROMPT_VERSION,
        "frozen_prompt": frozen.frozen_prompt_record(),
        "system_prompt": frozen.system_prompt,
        "user_prompt": frozen.user_prompt,
        "document_text": frozen.document_text,
        "retrieved_context": frozen.document_text,  # grounding context alias
        "reference_answer": reference_summary,
        "reference_summary": reference_summary,
        "reference_tags": (ref_item or {}).get("tags") if ref_item else None,
        "messages": shared_messages,
        "model_runs": model_runs,
    }

    payload: Dict[str, Any] = {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "workload": WORKLOAD_DOCUMENT_SUMMARIZATION,
            "prompt_version": SUMMARIZE_PROMPT_VERSION,
            "prompt_template_version": SUMMARIZE_PROMPT_VERSION,
            "document_freeze_version": DOCUMENT_FREEZE_VERSION,
            "retrieval_version": None,
            "timestamp": started,
            "timestamp_utc": started,
            "finished_utc": finished,
            "suite": profile.suite_id,
            "document_id": doc_id,
            "filename_hint": filename,
            "models": model_list,
            "participants": describe_participants(model_list),
            "dry_run": dry_run,
            "max_tokens": tok_budget,
            "temperature": temp,
            "quality_evaluator": evaluator_id,
            "reference_dataset_items": len(dataset),
            "dataset_path": dataset_path,
            "dataset_id": dataset_id,
            "prompt": prompt_metadata(),
            "protocol": {
                "freeze_document_once": True,
                "shared_messages_across_models": True,
                "consistency_gate_before_each_model": True,
                "system_router_uses_frozen_prompt": True,
                "identical_reference_summary_across_participants": True,
            },
            "isolation": {
                "generation_provider": (
                    "openai+nim"
                    if needs_openai and needs_system
                    else ("nvidia_nim" if needs_system else "openai")
                ),
                "uses_production_response_agent": False,
                "uses_production_nim_for_generation": needs_system,
                "uses_production_routing_decision": needs_system,
                "uses_production_http_endpoints": False,
                "uses_production_summarization_pipeline": False,
                "reuses_stored_chunks_readonly": True,
                "ui_entrypoint": False,
            },
        },
        "summary": {
            "questions": 1,
            "documents": 1,
            "models": len(model_list),
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "estimated_api_cost_usd": round(total_cost, 8),
            "total_api_cost_usd": round(total_cost, 8),
            "total_runtime_sec": round(wall_sec, 3),
            "workload": WORKLOAD_DOCUMENT_SUMMARIZATION,
        },
        "questions": [question_row],
    }

    results_path, summary_path, aggregates = write_run_with_summary(
        payload, out_dir=out_dir
    )
    # Enrich with average summary length (post-aggregate companion fields)
    for mid, stats in (aggregates.get("per_model") or {}).items():
        lengths = [
            float(r["summary_length"])
            for r in model_runs
            if (r.get("model") == mid or r.get("model_requested") == mid)
            and r.get("ok")
            and r.get("summary_length") is not None
            and not r.get("dry_run")
        ]
        stats["avg_summary_length"] = (
            round(sum(lengths) / len(lengths), 1) if lengths else None
        )
    summary_path.write_text(
        json.dumps(aggregates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    payload["aggregates"] = aggregates
    payload["metadata"]["results_path"] = str(results_path)
    payload["metadata"]["summary_path"] = str(summary_path)

    _print()
    _print(
        f"Done. cost≈${total_cost:.6f}  runtime={wall_sec:.1f}s  "
        f"results={results_path}"
    )
    return payload
