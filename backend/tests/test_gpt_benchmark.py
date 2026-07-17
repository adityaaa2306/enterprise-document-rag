"""Unit tests for the offline GPT benchmark framework (no live API spend)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.eval.gpt_benchmark.consistency import (
    BenchmarkConsistencyError,
    assert_identical_model_inputs,
    identity_from_frozen,
    verify_frozen_artifact,
)
from src.eval.gpt_benchmark.freeze import (
    FrozenBenchmarkInput,
    hash_context,
    hash_prompt,
)
from src.eval.gpt_benchmark.pricing import (
    estimate_api_cost_usd,
    energy_tier_for_model,
)
from src.eval.gpt_benchmark.prompts import build_frozen_messages
from src.eval.gpt_benchmark.questions import questions_for_suite
from src.eval.gpt_benchmark.store import write_run, write_run_with_summary
from src.eval.gpt_benchmark.summary import aggregate_per_model
from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    PROMPT_VERSION,
    RETRIEVAL_VERSION,
)


def _make_frozen(
    question: str = "What is the main purpose?",
    context: str = "The app tracks student attendance.",
    document_id: str = "doc-1",
    chunk_ids: list | None = None,
) -> FrozenBenchmarkInput:
    messages = build_frozen_messages(question, context)
    system = messages[0]["content"]
    user = messages[1]["content"]
    ids = chunk_ids if chunk_ids is not None else ["c1"]
    return FrozenBenchmarkInput(
        question=question,
        document_id=document_id,
        context_text=context,
        context_hash=hash_context(context),
        system_prompt=system,
        user_prompt=user,
        prompt_hash=hash_prompt(system, user),
        messages=messages,
        passage_chunk_ids=ids,
        chunk_count=len(ids),
        context_tokens=12,
    )


def test_smoke_suite_has_three_to_five_questions():
    qs = questions_for_suite("smoke")
    assert 3 <= len(qs) <= 5


def test_frozen_messages_identical_for_same_inputs():
    a = build_frozen_messages("What is this?", "CONTEXT BODY")
    b = build_frozen_messages("What is this?", "CONTEXT BODY")
    assert a == b
    assert a[0]["role"] == "system"
    assert "CONTEXT BODY" in a[1]["content"]
    assert "What is this?" in a[1]["content"]


def test_context_and_prompt_hash_stable():
    assert hash_context("hello") == hash_context("hello")
    assert hash_context("hello") != hash_context("hello!")
    assert hash_prompt("sys", "user") == hash_prompt("sys", "user")
    assert hash_prompt("sys", "user") != hash_prompt("sys", "user!")


def test_frozen_prompt_record_contains_required_fields():
    frozen = _make_frozen()
    rec = frozen.frozen_prompt_record()
    for key in (
        "system_prompt",
        "user_prompt",
        "retrieved_context",
        "prompt_hash",
        "context_hash",
    ):
        assert key in rec
        assert rec[key]


def test_verify_frozen_artifact_ok():
    frozen = _make_frozen()
    identity = verify_frozen_artifact(frozen)
    assert identity.context_hash == frozen.context_hash
    assert identity.prompt_hash == frozen.prompt_hash
    assert identity.chunk_count == 1


def test_verify_frozen_artifact_detects_tamper():
    frozen = _make_frozen()
    frozen.context_hash = "deadbeef"
    with pytest.raises(BenchmarkConsistencyError):
        verify_frozen_artifact(frozen)


def test_assert_identical_model_inputs_aborts_on_mismatch():
    frozen = _make_frozen()
    identity = identity_from_frozen(frozen)
    with pytest.raises(BenchmarkConsistencyError) as ei:
        assert_identical_model_inputs(
            expected=identity,
            document_id="other-doc",
            messages=frozen.messages,
            context_text=frozen.context_text,
            chunk_count=frozen.chunk_count,
            model="gpt-5-nano",
        )
    assert "document_id" in str(ei.value)


def test_pricing_and_tiers():
    assert estimate_api_cost_usd("gpt-5-nano", 1_000_000, 0) == 0.05
    assert estimate_api_cost_usd("gpt-5-mini", 0, 1_000_000) == 2.0
    assert estimate_api_cost_usd("gpt-5.5", 1_000_000, 1_000_000) == 35.0
    assert energy_tier_for_model("gpt-5-nano") == "light"
    assert energy_tier_for_model("gpt-5-mini") == "medium"
    assert energy_tier_for_model("gpt-5.5") == "heavy"


def test_write_run_creates_json(tmp_path: Path):
    path = write_run(
        {
            "metadata": {
                "benchmark_version": BENCHMARK_VERSION,
                "prompt_version": PROMPT_VERSION,
                "retrieval_version": RETRIEVAL_VERSION,
            },
            "summary": {"questions": 1},
        },
        out_dir=tmp_path,
        filename="unit_test_run.json",
    )
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert BENCHMARK_VERSION in text
    assert PROMPT_VERSION in text


def test_aggregate_and_summary_file(tmp_path: Path):
    payload = {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "prompt_version": PROMPT_VERSION,
            "retrieval_version": RETRIEVAL_VERSION,
            "timestamp_utc": "2026-07-17T00:00:00+00:00",
            "models": ["gpt-5-nano", "gpt-5-mini"],
            "document_id": "doc-1",
        },
        "summary": {
            "questions": 2,
            "models": 2,
            "estimated_api_cost_usd": 0.01,
            "total_runtime_sec": 12.5,
            "total_prompt_tokens": 100,
            "total_completion_tokens": 40,
            "total_tokens": 140,
        },
        "questions": [
            {
                "question": "Q1",
                "model_runs": [
                    {
                        "model": "gpt-5-nano",
                        "ok": True,
                        "latency_ms": 100,
                        "ttft_ms": 20,
                        "tokens_per_sec": 50,
                        "prompt_tokens": 40,
                        "completion_tokens": 10,
                        "estimated_api_cost_usd": 0.001,
                        "estimated_energy_wh": 0.01,
                        "estimated_co2e_g": 0.002,
                    },
                    {
                        "model": "gpt-5-mini",
                        "ok": True,
                        "latency_ms": 200,
                        "ttft_ms": 40,
                        "tokens_per_sec": 40,
                        "prompt_tokens": 40,
                        "completion_tokens": 20,
                        "estimated_api_cost_usd": 0.004,
                        "estimated_energy_wh": 0.02,
                        "estimated_co2e_g": 0.004,
                    },
                ],
            },
            {
                "question": "Q2",
                "model_runs": [
                    {
                        "model": "gpt-5-nano",
                        "ok": True,
                        "latency_ms": 300,
                        "ttft_ms": 30,
                        "tokens_per_sec": 60,
                        "prompt_tokens": 50,
                        "completion_tokens": 15,
                        "estimated_api_cost_usd": 0.002,
                        "estimated_energy_wh": 0.015,
                        "estimated_co2e_g": 0.003,
                    },
                    {
                        "model": "gpt-5-mini",
                        "ok": True,
                        "latency_ms": 400,
                        "ttft_ms": 50,
                        "tokens_per_sec": 35,
                        "prompt_tokens": 50,
                        "completion_tokens": 25,
                        "estimated_api_cost_usd": 0.003,
                        "estimated_energy_wh": 0.025,
                        "estimated_co2e_g": 0.005,
                    },
                ],
            },
        ],
    }
    results_path, summary_path, aggregates = write_run_with_summary(
        payload, out_dir=tmp_path, filename="agg_test.json"
    )
    assert results_path.is_file()
    assert summary_path.is_file()
    assert summary_path.name.endswith("_summary.json")

    nano = aggregates["per_model"]["gpt-5-nano"]
    assert nano["n_ok"] == 2
    assert nano["avg_latency_ms"] == 200.0
    assert nano["p50_latency_ms"] == 200.0
    assert nano["avg_ttft_ms"] == 25.0
    assert aggregates["totals"]["total_runtime_sec"] == 12.5

    # Direct aggregate helper matches companion file contents
    again = aggregate_per_model(payload)
    assert again["per_model"]["gpt-5-mini"]["avg_prompt_tokens"] == 45.0


def test_api_router_requires_token():
    from fastapi import HTTPException

    from src.eval.gpt_benchmark.api import _require_benchmark_token

    with patch.dict("os.environ", {"BENCHMARK_ADMIN_TOKEN": "secret"}, clear=False):
        try:
            _require_benchmark_token(None)
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 403
        _require_benchmark_token("secret")


@patch("src.eval.gpt_benchmark.runner.bootstrap_retrieval_runtime")
@patch("src.eval.gpt_benchmark.runner.freeze_retrieval")
@patch("src.eval.gpt_benchmark.runner.resolve_document_id", return_value="doc-1")
def test_dry_run_no_openai_client(mock_resolve, mock_freeze, mock_boot, tmp_path: Path):
    from src.eval.gpt_benchmark.runner import run_benchmark

    frozen = _make_frozen()
    mock_freeze.return_value = frozen

    with patch("src.eval.gpt_benchmark.runner.get_openai_client") as mock_client:
        payload = run_benchmark(
            document_id="doc-1",
            suite="smoke",
            models=["gpt-5-nano", "gpt-5-mini"],
            questions=["What is the main purpose?"],
            dry_run=True,
            out_dir=tmp_path,
        )
        mock_client.assert_not_called()

    # Retrieval called exactly once for the single question
    assert mock_freeze.call_count == 1
    assert payload["metadata"]["retrieval_calls_total"] == 1
    assert payload["metadata"]["dry_run"] is True
    assert payload["metadata"]["benchmark_version"] == BENCHMARK_VERSION

    q0 = payload["questions"][0]
    assert q0["context_hash"] == frozen.context_hash
    assert q0["prompt_hash"] == frozen.prompt_hash
    assert q0["chunk_count"] == frozen.chunk_count
    assert "system_prompt" in q0
    assert "user_prompt" in q0
    assert "retrieved_context" in q0

    # Both models share identical verification hashes
    hashes = {
        (
            r["input_verification"]["context_hash"],
            r["input_verification"]["prompt_hash"],
            r["input_verification"]["chunk_count"],
            r["input_verification"]["document_id"],
        )
        for r in q0["model_runs"]
    }
    assert len(hashes) == 1

    assert Path(payload["metadata"]["results_path"]).is_file()
    assert Path(payload["metadata"]["summary_path"]).is_file()
    assert "per_model" in payload["aggregates"]


@patch("src.eval.gpt_benchmark.runner.bootstrap_retrieval_runtime")
@patch("src.eval.gpt_benchmark.runner.freeze_retrieval")
@patch("src.eval.gpt_benchmark.runner.resolve_document_id", return_value="doc-1")
def test_consistency_abort_on_mutated_messages(
    mock_resolve, mock_freeze, mock_boot, tmp_path: Path
):
    from src.eval.gpt_benchmark.runner import run_benchmark

    frozen = _make_frozen()
    mock_freeze.return_value = frozen

    # Mutate after freeze verification path: replace messages content before model loop
    # by returning a frozen object whose messages already mismatch prompts.
    frozen.messages = [
        {"role": "system", "content": "TAMPERED"},
        {"role": "user", "content": frozen.user_prompt},
    ]

    with pytest.raises(BenchmarkConsistencyError):
        run_benchmark(
            document_id="doc-1",
            suite="smoke",
            models=["gpt-5-nano"],
            questions=["What is the main purpose?"],
            dry_run=True,
            out_dir=tmp_path,
        )


def test_production_settings_do_not_require_openai_key():
    """Benchmark OPENAI_API_KEY must not be a required production Settings field."""
    from src.core.config import Settings

    fields = getattr(Settings, "model_fields", {}) or {}
    assert "OPENAI_API_KEY" not in fields


def test_dashboard_export_has_chart_keys():
    from src.eval.gpt_benchmark.dashboard_export import build_dashboard_payload

    results = {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "prompt_version": PROMPT_VERSION,
            "retrieval_version": RETRIEVAL_VERSION,
            "document_id": "doc-1",
            "timestamp_utc": "2026-07-17T00:00:00+00:00",
            "models": ["gpt-5-nano", "gpt-5-mini"],
            "suite": "smoke",
        },
        "summary": {
            "questions": 1,
            "total_api_cost_usd": 0.01,
            "total_runtime_sec": 3.0,
            "total_prompt_tokens": 10,
            "total_completion_tokens": 5,
            "total_tokens": 15,
        },
        "questions": [
            {
                "question": "Q1",
                "document_id": "doc-1",
                "context_hash": "abc",
                "prompt_hash": "def",
                "chunk_count": 2,
            }
        ],
    }
    aggregates = {
        "per_model": {
            "gpt-5-nano": {
                "avg_latency_ms": 100,
                "p50_latency_ms": 100,
                "p95_latency_ms": 100,
                "avg_ttft_ms": 20,
                "avg_tokens_per_sec": 40,
                "avg_prompt_tokens": 10,
                "avg_completion_tokens": 5,
                "avg_estimated_api_cost_usd": 0.001,
                "total_estimated_api_cost_usd": 0.001,
                "avg_estimated_energy_wh": 0.01,
                "avg_estimated_co2e_g": 0.002,
            },
            "gpt-5-mini": {
                "avg_latency_ms": 200,
                "p50_latency_ms": 200,
                "p95_latency_ms": 200,
                "avg_ttft_ms": 40,
                "avg_tokens_per_sec": 30,
                "avg_prompt_tokens": 10,
                "avg_completion_tokens": 8,
                "avg_estimated_api_cost_usd": 0.004,
                "total_estimated_api_cost_usd": 0.004,
                "avg_estimated_energy_wh": 0.02,
                "avg_estimated_co2e_g": 0.004,
            },
        }
    }
    dash = build_dashboard_payload(
        campaign_id="campaign_test",
        results_payload=results,
        aggregates=aggregates,
    )
    for key in (
        "latency_comparison",
        "ttft_comparison",
        "tokens_per_sec",
        "prompt_vs_completion_tokens",
        "estimated_cost",
        "estimated_energy",
        "estimated_co2e",
    ):
        assert key in dash["charts"]
    assert dash["highlights"]["fastest_model"]["model"] == "gpt-5-nano"
    assert dash["highlights"]["lowest_estimated_cost"]["model"] == "gpt-5-nano"
    assert dash["reproducibility"]["document_id"] == "doc-1"


def test_markdown_report_contains_sections():
    from src.eval.gpt_benchmark.dashboard_export import build_dashboard_payload
    from src.eval.gpt_benchmark.report import render_markdown_report

    results = {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "prompt_version": PROMPT_VERSION,
            "retrieval_version": RETRIEVAL_VERSION,
            "document_id": "doc-1",
            "timestamp_utc": "2026-07-17T00:00:00+00:00",
            "finished_utc": "2026-07-17T00:01:00+00:00",
            "models": ["gpt-5-nano"],
            "suite": "smoke",
            "dry_run": True,
        },
        "summary": {
            "questions": 1,
            "models": 1,
            "total_api_cost_usd": 0.01,
            "total_runtime_sec": 2.5,
            "total_prompt_tokens": 10,
            "total_completion_tokens": 0,
            "total_tokens": 10,
        },
        "questions": [
            {
                "question": "What is the main purpose?",
                "context_hash": "a" * 64,
                "prompt_hash": "b" * 64,
                "chunk_count": 1,
            }
        ],
    }
    aggregates = {
        "per_model": {
            "gpt-5-nano": {
                "avg_latency_ms": None,
                "p50_latency_ms": None,
                "p95_latency_ms": None,
                "avg_ttft_ms": None,
                "avg_tokens_per_sec": None,
                "avg_prompt_tokens": 10,
                "avg_completion_tokens": 0,
                "total_estimated_api_cost_usd": 0.01,
                "avg_estimated_energy_wh": None,
                "avg_estimated_co2e_g": None,
            }
        }
    }
    dash = build_dashboard_payload(
        campaign_id="campaign_md",
        results_payload=results,
        aggregates=aggregates,
    )
    md = render_markdown_report(
        campaign_id="campaign_md",
        config={"max_tokens": 500, "temperature": 0.2},
        results_payload=results,
        aggregates=aggregates,
        dashboard=dash,
    )
    assert "# GPT Benchmark Report" in md
    assert "Benchmark methodology" in md
    assert "Per-model statistics" in md
    assert "gpt-5-nano" in md


@patch("src.eval.gpt_benchmark.runner.bootstrap_retrieval_runtime")
@patch("src.eval.gpt_benchmark.runner.freeze_retrieval")
@patch("src.eval.gpt_benchmark.runner.resolve_document_id", return_value="doc-1")
def test_run_campaign_writes_versioned_artifacts(
    mock_resolve, mock_freeze, mock_boot, tmp_path: Path
):
    from src.eval.gpt_benchmark.campaign import run_campaign

    frozen = _make_frozen()
    mock_freeze.return_value = frozen

    outcome = run_campaign(
        document_id="doc-1",
        suite="smoke",
        models=["gpt-5-nano"],
        questions=["What is the main purpose?"],
        dry_run=True,
        label="unit",
        campaigns_root=tmp_path / "campaigns",
    )

    root = Path(outcome["campaign_root"])
    assert root.is_dir()
    for name in (
        "config.json",
        "metadata.json",
        "results.json",
        "summary.json",
        "dashboard.json",
        "REPORT.md",
        "execution.log",
    ):
        assert (root / name).is_file(), name

    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    assert meta["benchmark_version"] == BENCHMARK_VERSION
    assert meta["prompt_version"] == PROMPT_VERSION
    assert meta["retrieval_version"] == RETRIEVAL_VERSION
    assert meta["document_id"] == "doc-1"
    assert meta["context_and_prompt_hashes"][0]["context_hash"] == frozen.context_hash
    assert meta["context_and_prompt_hashes"][0]["prompt_hash"] == frozen.prompt_hash

    dash = json.loads((root / "dashboard.json").read_text(encoding="utf-8"))
    assert "latency_comparison" in dash["charts"]

    # Never overwrite: second campaign gets a distinct directory
    outcome2 = run_campaign(
        document_id="doc-1",
        suite="smoke",
        models=["gpt-5-nano"],
        questions=["What is the main purpose?"],
        dry_run=True,
        label="unit",
        campaigns_root=tmp_path / "campaigns",
    )
    assert outcome2["campaign_root"] != outcome["campaign_root"]
    assert Path(outcome2["campaign_root"]).is_dir()


def test_participant_normalization_includes_router():
    from src.eval.gpt_benchmark.participants import (
        DEFAULT_BENCHMARK_PARTICIPANTS,
        INTELLIGENT_ROUTER_ID,
        display_name,
        is_system_participant,
        normalize_participants,
    )

    assert is_system_participant("Intelligent Router")
    assert is_system_participant("intelligent-router")
    assert normalize_participants(["router", "gpt-5-nano"]) == [
        INTELLIGENT_ROUTER_ID,
        "gpt-5-nano",
    ]
    assert INTELLIGENT_ROUTER_ID in DEFAULT_BENCHMARK_PARTICIPANTS
    assert display_name(INTELLIGENT_ROUTER_ID) == "Intelligent Router"


def test_system_runner_dry_run_uses_frozen_messages_and_routing():
    from src.eval.gpt_benchmark.system_runner import run_intelligent_router

    frozen = _make_frozen()
    rd = {
        "selected_model": "meta/llama-3.1-8b-instruct",
        "tier": "light",
        "compile_tier": "heavy",
        "fallbacks": ["meta/llama-3.1-8b-instruct"],
        "compile_fallbacks": ["meta/llama-3.3-70b-instruct"],
        "mode": "automatic",
        "reason_summary": "unit-test routing",
        "policy_version": "test",
    }
    run = run_intelligent_router(
        document_id="doc-1",
        question=frozen.question,
        messages=frozen.messages,
        context_tokens=frozen.context_tokens,
        retrieval_hits=frozen.chunk_count,
        max_tokens=100,
        temperature=0.2,
        input_verification={"verified": True},
        dry_run=True,
        routing_decision=rd,
    )
    row = run.to_dict()
    assert row["ok"] is True
    assert row["dry_run"] is True
    assert row["model"] == "intelligent-router"
    assert row["participant_kind"] == "system_router"
    assert row["routing"]["selected_model"] == "meta/llama-3.1-8b-instruct"
    assert row["routing"]["http_bypassed"] is True
    assert row["routing"]["execution_path"] == "in_process_nim_via_routing_decision"
    assert row["input_verification"]["verified"] is True


def test_system_runner_live_maps_timing_schema():
    from src.eval.gpt_benchmark.system_runner import run_intelligent_router

    frozen = _make_frozen()
    rd = {
        "selected_model": "meta/llama-3.1-8b-instruct",
        "compile_fallbacks": ["meta/llama-3.1-8b-instruct"],
        "mode": "automatic",
    }

    def _fake_call(model_ids, messages, **kwargs):
        assert messages is frozen.messages
        assert "meta/llama-3.1-8b-instruct" in model_ids
        return (
            "Router answer text",
            "meta/llama-3.1-8b-instruct",
            {"ttft_ms": 120.0, "ttlt_ms": 400.0, "mode": "stream"},
        )

    with (
        patch(
            "src.agents.models.get_nim_client",
            return_value=object(),
        ),
        patch(
            "src.agents.models.call_chat_with_fallback",
            side_effect=_fake_call,
        ),
        patch(
            "src.agents.models.strip_outer_markdown_fence",
            side_effect=lambda t: t,
        ),
        patch(
            "src.eval.gpt_benchmark.openai_client._attach_energy",
            autospec=True,
        ),
    ):
        run = run_intelligent_router(
            document_id="doc-1",
            question=frozen.question,
            messages=frozen.messages,
            context_tokens=12,
            retrieval_hits=1,
            max_tokens=50,
            routing_decision=rd,
            dry_run=False,
        )

    row = run.to_dict()
    assert row["ok"] is True
    assert row["answer"] == "Router answer text"
    assert row["model_returned"] == "meta/llama-3.1-8b-instruct"
    assert row["ttft_ms"] == 120.0
    assert row["prompt_tokens"] > 0
    assert row["completion_tokens"] > 0
    assert "latency_ms" in row
    assert row["routing"]["model_used"] == "meta/llama-3.1-8b-instruct"


def test_nim_pricing_estimate():
    cost = estimate_api_cost_usd("meta/llama-3.1-8b-instruct", 1_000_000, 0)
    assert cost == pytest.approx(0.06)
    assert energy_tier_for_model("meta/llama-3.3-70b-instruct") == "heavy"
