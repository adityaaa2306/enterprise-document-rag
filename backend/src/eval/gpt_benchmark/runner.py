"""
Orchestrate offline GPT benchmarks.

Scientific protocol per question:
  1. Retrieve + assemble context **once**
  2. Freeze system/user prompt + context hashes
  3. Verify frozen identity before **every** model call
  4. Run selected models sequentially on identical messages
  5. Persist full JSON + auto-generated per-model summary
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.eval.gpt_benchmark.consistency import (
    BenchmarkConsistencyError,
    assert_identical_model_inputs,
    verify_frozen_artifact,
)
from src.eval.gpt_benchmark.freeze import (
    freeze_retrieval,
    frozen_input_fingerprint,
    resolve_document_id,
)
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
from src.eval.gpt_benchmark.prompts import prompt_metadata
from src.eval.gpt_benchmark.quality.attach import evaluate_run_quality
from src.eval.gpt_benchmark.quality.registry import DEFAULT_EVALUATOR_ID
from src.eval.gpt_benchmark.dataset import reference_for_question, resolve_dataset
from src.eval.gpt_benchmark.questions import SMOKE_DOCUMENT_FILENAME, questions_for_suite
from src.eval.gpt_benchmark.store import write_run_with_summary
from src.eval.gpt_benchmark.system_runner import run_intelligent_router
from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    PROMPT_VERSION,
    RETRIEVAL_VERSION,
)

log = logging.getLogger(__name__)


def bootstrap_retrieval_runtime() -> None:
    """
    Initialize storage + NIM embeddings client required by RetrievalService.

    Does not wire benchmark generation into the production ResponseAgent path.
    """
    from src.agents import models as models_mod
    from src.memory import storage

    models_mod.load_all_models()
    storage.init_database(block_on_chroma=False)
    if models_mod.get_nim_client() is None:
        raise RuntimeError(
            "NVIDIA_API_KEY is required for retrieval embeddings/rerank during "
            "benchmarking. Generation still uses OPENAI_API_KEY separately."
        )


def _print(msg: str = "") -> None:
    """Developer-facing progress (always visible; not gated by log level)."""
    print(msg, flush=True)


def _attach_quality(
    row: Dict[str, Any],
    *,
    question: str,
    reference_answer: Optional[str],
    context: str,
    evaluator_id: str,
    dry_run: bool,
) -> None:
    """Mutate model_run row with quality block (identical refs for all participants)."""
    quality = evaluate_run_quality(
        question=question,
        reference_answer=reference_answer,
        candidate_answer=str(row.get("answer") or ""),
        context=context,
        evaluator_id=evaluator_id,
        dry_run=dry_run or bool(row.get("dry_run")),
    )
    row["quality"] = quality
    # Flat aliases for table consumers / exports
    for key in (
        "quality_score",
        "correctness",
        "completeness",
        "groundedness",
        "conciseness",
    ):
        row[key] = quality.get(key)


def run_benchmark(
    *,
    document_id: Optional[str] = None,
    filename: Optional[str] = None,
    suite: str = "smoke",
    models: Optional[Sequence[str]] = None,
    questions: Optional[Sequence[str]] = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
    dry_run: bool = False,
    out_dir: Optional[Path] = None,
    assemble_tier: str = "heavy",
    dataset_path: Optional[str] = None,
    dataset_id: Optional[str] = None,
    quality_evaluator: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a benchmark run and write JSON results + summary.

    ``dry_run`` freezes retrieval/prompts and estimates cost from prompt size
    only — no OpenAI completion calls (safe credit check). Consistency checks
    still run so dry-runs validate the freeze protocol.
    """
    doc_id = resolve_document_id(
        document_id=document_id,
        filename=filename or (SMOKE_DOCUMENT_FILENAME if suite == "smoke" else None),
    )
    model_list = normalize_participants(
        list(models) if models is not None else list(DEFAULT_BENCHMARK_PARTICIPANTS)
    )
    q_list = list(questions) if questions is not None else questions_for_suite(suite)
    needs_openai = any(not is_system_participant(m) for m in model_list)
    needs_system = any(is_system_participant(m) for m in model_list)
    evaluator_id = (quality_evaluator or DEFAULT_EVALUATOR_ID).strip()
    dataset = resolve_dataset(
        suite=suite, dataset_path=dataset_path, dataset_id=dataset_id
    )

    bootstrap_retrieval_runtime()
    client = None
    if not dry_run and needs_openai:
        client = get_openai_client()

    started_dt = datetime.now(timezone.utc)
    started = started_dt.isoformat()
    wall_t0 = time.perf_counter()

    question_rows: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    retrieval_calls = 0

    _print(
        f"GPT benchmark v{BENCHMARK_VERSION} — suite={suite} "
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

    for qi, question in enumerate(q_list, start=1):
        _print(f"Benchmark {qi}/{len(q_list)}")
        _print(f"Question: {question}")

        ref_item = reference_for_question(question, dataset)
        reference_answer = (
            (ref_item or {}).get("reference_answer") if ref_item else None
        )
        if isinstance(reference_answer, str):
            reference_answer = reference_answer.strip() or None
        if reference_answer:
            _print("  reference_answer ✓")
        else:
            _print("  reference_answer — (quality will be skipped for this question)")

        # --- 1) Retrieve exactly once ---
        frozen = freeze_retrieval(
            document_id=doc_id,
            question=question,
            assemble_tier=assemble_tier,
        )
        retrieval_calls += 1
        _print("Retrieval frozen ✓")
        _print(f"  context_hash={frozen.context_hash}")
        _print(f"  chunk_count={frozen.chunk_count}")

        # --- 2) Freeze / verify complete prompt ---
        identity = verify_frozen_artifact(frozen)
        input_fp = frozen_input_fingerprint(frozen)
        _print("Prompt frozen ✓")
        _print(f"  prompt_hash={frozen.prompt_hash}")

        if not frozen.context_text.strip():
            _print("  ⚠ empty context — skipping models for this question")
            question_rows.append(
                {
                    "question": question,
                    "ok": False,
                    "error": "No relevant context found for this query.",
                    "document_id": doc_id,
                    "context_hash": frozen.context_hash,
                    "prompt_hash": frozen.prompt_hash,
                    "chunk_count": frozen.chunk_count,
                    "frozen_prompt": frozen.frozen_prompt_record(),
                    "model_runs": [],
                }
            )
            _print()
            continue

        _print("Running:")
        for m in model_list:
            kind = participant_kind(m)
            _print(f"  • {display_name(m)} ({kind})")

        hits = frozen.chunk_count
        model_runs: List[Dict[str, Any]] = []

        # Capture the exact message object reference once; every participant reuses it.
        shared_messages = frozen.messages

        for model in model_list:
            # --- Consistency gate before every participant ---
            verification = assert_identical_model_inputs(
                expected=identity,
                document_id=doc_id,
                messages=shared_messages,
                context_text=frozen.context_text,
                chunk_count=frozen.chunk_count,
                model=model,
            )
            if shared_messages is not frozen.messages:
                raise BenchmarkConsistencyError(
                    f"Aborting before participant={model!r}: messages list was replaced"
                )

            if is_system_participant(model):
                run = run_intelligent_router(
                    document_id=doc_id,
                    question=question,
                    messages=shared_messages,
                    context_tokens=frozen.context_tokens,
                    retrieval_hits=hits,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    input_verification=verification,
                    dry_run=dry_run,
                )
                row = run.to_dict()
                _attach_quality(
                    row,
                    question=question,
                    reference_answer=reference_answer,
                    context=frozen.context_text,
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
                        f"    ✓ {label}  "
                        f"lat={run.latency_ms:.0f}ms  "
                        f"ttft={run.ttft_ms if run.ttft_ms is not None else 'n/a'}  "
                        f"via={run.model_returned or '—'}  "
                        f"tok={run.total_tokens}  "
                        f"${run.estimated_api_cost_usd:.6f}{qtxt}"
                    )
                else:
                    _print(f"    ✗ {label}  error={run.error}")
                continue

            if dry_run:
                prompt_blob = "\n".join(m.get("content") or "" for m in shared_messages)
                est_prompt = max(0, len(prompt_blob) // 4)
                est_cost = estimate_api_cost_usd(model, est_prompt, max_tokens)
                row = {
                    "model": model,
                    "model_requested": model,
                    "model_returned": None,
                    "ok": True,
                    "dry_run": True,
                    "participant_kind": "openai",
                    "finish_reason": None,
                    "prompt_tokens": est_prompt,
                    "prompt_tokens_estimate": est_prompt,
                    "completion_tokens": 0,
                    "completion_tokens_budget": max_tokens,
                    "total_tokens": est_prompt,
                    "latency_ms": None,
                    "ttft_ms": None,
                    "tokens_per_sec": None,
                    "estimated_api_cost_usd": 0.0,
                    "estimated_api_cost_usd_upper_bound": round(est_cost, 8),
                    "input_verification": verification,
                    "routing": {},
                    "answer": "",
                    "note": (
                        "Dry-run: no OpenAI call. Cost upper-bound assumes "
                        f"full max_tokens={max_tokens} completion."
                    ),
                }
                _attach_quality(
                    row,
                    question=question,
                    reference_answer=reference_answer,
                    context=frozen.context_text,
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
                query=question,
                context_tokens=frozen.context_tokens,
                retrieval_hits=hits,
                max_tokens=max_tokens,
                temperature=temperature,
                input_verification=verification,
            )
            row = run.to_dict()
            _attach_quality(
                row,
                question=question,
                reference_answer=reference_answer,
                context=frozen.context_text,
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
                    f"    ✓ {model}  "
                    f"lat={run.latency_ms:.0f}ms  "
                    f"ttft={run.ttft_ms if run.ttft_ms is not None else '—'}  "
                    f"tok={run.total_tokens}  "
                    f"${run.estimated_api_cost_usd:.6f}{qtxt}"
                )
            else:
                _print(f"    ✗ {model}  error={run.error}")

        # Post-model: ensure every successful run recorded the same hashes
        for row in model_runs:
            ver = row.get("input_verification") or {}
            if not ver.get("verified"):
                continue
            if ver.get("context_hash") != frozen.context_hash:
                raise BenchmarkConsistencyError(
                    "Stored model run context_hash diverged from freeze"
                )
            if ver.get("prompt_hash") != frozen.prompt_hash:
                raise BenchmarkConsistencyError(
                    "Stored model run prompt_hash diverged from freeze"
                )

        question_rows.append(
            {
                "question": question,
                "ok": True,
                "document_id": doc_id,
                "context_hash": frozen.context_hash,
                "prompt_hash": frozen.prompt_hash,
                "input_fingerprint": input_fp,
                "context_tokens": frozen.context_tokens,
                "chunk_count": frozen.chunk_count,
                "passage_chunk_ids": frozen.passage_chunk_ids,
                "retrieval_version": frozen.retrieval_version,
                "prompt_version": frozen.prompt_version,
                "frozen_prompt": frozen.frozen_prompt_record(),
                "system_prompt": frozen.system_prompt,
                "user_prompt": frozen.user_prompt,
                "retrieved_context": frozen.context_text,
                "reference_answer": reference_answer,
                "reference_tags": (ref_item or {}).get("tags") if ref_item else None,
                "messages": shared_messages,
                "retrieval_calls_for_question": 1,
                "model_runs": model_runs,
            }
        )
        _print()

    wall_sec = time.perf_counter() - wall_t0
    finished = datetime.now(timezone.utc).isoformat()

    # Scientific integrity: one retrieval call per question processed
    if retrieval_calls != len(q_list):
        raise BenchmarkConsistencyError(
            f"Expected {len(q_list)} retrieval calls, recorded {retrieval_calls}"
        )

    payload: Dict[str, Any] = {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "workload": "interactive_rag",
            "prompt_version": PROMPT_VERSION,
            "prompt_template_version": PROMPT_VERSION,
            "retrieval_version": RETRIEVAL_VERSION,
            "timestamp": started,
            "timestamp_utc": started,
            "finished_utc": finished,
            "suite": suite,
            "document_id": doc_id,
            "filename_hint": filename,
            "models": model_list,
            "participants": describe_participants(model_list),
            "dry_run": dry_run,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "assemble_tier": assemble_tier,
            "quality_evaluator": evaluator_id,
            "reference_dataset_items": len(dataset),
            "dataset_path": dataset_path,
            "dataset_id": dataset_id,
            "prompt": prompt_metadata(),
            "retrieval_calls_total": retrieval_calls,
            "protocol": {
                "retrieve_once_per_question": True,
                "shared_messages_across_models": True,
                "consistency_gate_before_each_model": True,
                "system_router_uses_frozen_prompt": True,
                "identical_reference_answer_across_participants": True,
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
                "reuses_production_retrieval": True,
                "ui_entrypoint": False,
            },
        },
        "summary": {
            "questions": len(q_list),
            "models": len(model_list),
            "participants": len(model_list),
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "estimated_api_cost_usd": round(total_cost, 8),
            "total_api_cost_usd": round(total_cost, 8),
            "total_runtime_sec": round(wall_sec, 3),
            "retrieval_calls_total": retrieval_calls,
        },
        "questions": question_rows,
    }

    results_path, summary_path, aggregates = write_run_with_summary(
        payload, out_dir=out_dir
    )
    payload["metadata"]["results_path"] = str(results_path)
    payload["metadata"]["summary_path"] = str(summary_path)
    payload["aggregates"] = aggregates

    _print("=== BENCHMARK COMPLETE ===")
    _print(f"Total API cost: ${round(total_cost, 6):.6f}")
    _print(f"Total runtime:  {wall_sec:.2f}s")
    _print(f"Output dir:     {results_path.parent}")
    _print(f"Results file:   {results_path}")
    _print(f"Summary file:   {summary_path}")
    log.info("Wrote benchmark results to %s (summary %s)", results_path, summary_path)
    return payload
