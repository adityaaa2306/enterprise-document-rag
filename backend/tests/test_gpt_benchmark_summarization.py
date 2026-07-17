"""Unit tests for document summarization benchmark workload (no API spend)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.eval.gpt_benchmark.consistency import assert_identical_model_inputs
from src.eval.gpt_benchmark.summarize.consistency import verify_frozen_summarization
from src.eval.gpt_benchmark.summarize.dataset import (
    ATTENDANCE_SUMMARIZATION_DATASET,
    extract_reference_summary,
    reference_for_document,
    resolve_summarization_dataset,
)
from src.eval.gpt_benchmark.summarize.freeze import (
    FrozenSummarizationInput,
    _apply_suite_window,
    freeze_document_for_summarization,
)
from src.eval.gpt_benchmark.summarize.prompts import (
    SUMMARIZATION_TASK_LABEL,
    build_summarization_messages,
)
from src.eval.gpt_benchmark.summarize.suites import list_summarization_suites, suite_profile
from src.eval.gpt_benchmark.versions import (
    BENCHMARK_VERSION,
    SUMMARIZE_PROMPT_VERSION,
)
from src.eval.gpt_benchmark.workloads import (
    WORKLOAD_DOCUMENT_SUMMARIZATION,
    WORKLOAD_INTERACTIVE_RAG,
    is_summarization_suite,
    workload_for_suite,
)


def test_workload_inference():
    assert workload_for_suite("smoke") == WORKLOAD_INTERACTIVE_RAG
    assert workload_for_suite("summarization-smoke") == WORKLOAD_DOCUMENT_SUMMARIZATION
    assert is_summarization_suite("summarize-standard")


def test_suite_profiles():
    suites = list_summarization_suites()
    assert "summarization-smoke" in suites
    assert "summarization-standard" in suites
    assert "summarization-large" in suites
    smoke = suite_profile("summarization-smoke")
    assert smoke.max_chunks == 12
    assert smoke.max_tokens == 500


def test_summarization_messages_frozen():
    msgs = build_summarization_messages("Hello world document.")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "Hello world document." in msgs[1]["content"]
    assert SUMMARIZATION_TASK_LABEL


def test_suite_window_truncates_chunks():
    rows = [{"index": i, "text": f"chunk-{i} " + ("x" * 20)} for i in range(20)]
    profile = suite_profile("summarization-smoke")
    boundaries, text = _apply_suite_window(rows, profile)
    assert len(boundaries) <= 12
    assert len(text) <= (profile.max_chars or 10**9)


def test_freeze_document_mocked():
    chunks = [
        {"index": "0", "text": "Alpha section about attendance."},
        {"index": "1", "text": "Beta section about percentages."},
    ]
    with patch(
        "src.memory.storage.retrieve_chunks",
        return_value=chunks,
    ):
        frozen = freeze_document_for_summarization(
            document_id="doc-test",
            suite="summarization-smoke",
            filename="Student Attendance App.pdf",
        )
    assert isinstance(frozen, FrozenSummarizationInput)
    assert frozen.document_id == "doc-test"
    assert frozen.chunk_count == 2
    assert "Alpha section" in frozen.document_text
    identity = verify_frozen_summarization(frozen)
    assert identity.context_hash == frozen.context_hash
    assert_identical_model_inputs(
        expected=identity,
        document_id="doc-test",
        messages=frozen.messages,
        context_text=frozen.document_text,
        chunk_count=frozen.chunk_count,
        model="gpt-5-nano",
        prompt_version=SUMMARIZE_PROMPT_VERSION,
    )


def test_reference_dataset():
    items = resolve_summarization_dataset(suite="summarization-smoke")
    assert len(items) >= 1
    ref = reference_for_document(
        document_id="any",
        filename="Student Attendance App.pdf",
        dataset=items,
    )
    summary = extract_reference_summary(ref)
    assert summary
    assert "attendance" in summary.lower()
    assert ATTENDANCE_SUMMARIZATION_DATASET


def test_benchmark_version_bumped():
    assert BENCHMARK_VERSION.startswith("1.4")


def test_empty_chunks_raises():
    with patch("src.memory.storage.retrieve_chunks", return_value=[]):
        with pytest.raises(FileNotFoundError):
            freeze_document_for_summarization(
                document_id="missing",
                suite="summarization-smoke",
            )
