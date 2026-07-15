"""Tests for NIM timeout / transient error classification and optional FEA."""
from __future__ import annotations

import pytest


def test_is_transient_nim_error_timeout():
    from src.agents.models import NimApiError, is_transient_nim_error

    assert is_transient_nim_error(TimeoutError("timed out"))
    assert is_transient_nim_error(NimApiError("NIM timeout", status_code=504))
    assert is_transient_nim_error(RuntimeError("504 Gateway Timeout"))
    assert is_transient_nim_error(RuntimeError("Connection reset by peer"))
    assert not is_transient_nim_error(ValueError("bad json"))


def test_default_features_always_usable():
    from src.agents.feature_extraction import default_features

    feats = default_features([], {}, reason="unit_test")
    assert feats["document_type"]
    assert feats["domain_label"]
    assert "retrieval_confidence" in feats
    assert feats["classifier_method"].startswith("default_metadata")


def test_extract_features_survives_llm_failure(monkeypatch):
    from src.agents import feature_extraction, models

    class DummyChunk:
        content = "This is a short general document about nothing in particular."

    def boom(*_a, **_k):
        raise models.NimApiError("NIM HTTP 504 calling model", status_code=504)

    monkeypatch.setattr(models, "get_nim_client", lambda: object())
    monkeypatch.setattr(models, "call_chat_with_fallback", boom)
    monkeypatch.setattr(
        feature_extraction,
        "retrieval_confidence_probe",
        lambda _c: {"retrieval_confidence": 0.5, "retrieval_method": "stub"},
    )

    feats = feature_extraction.extract_features([DummyChunk()], {"strategy": "fast"})
    assert feats["classifier_method"] in (
        "heuristic_fallback",
        "default_metadata:NimApiError",
    ) or feats["classifier_method"].startswith("heuristic") or feats[
        "classifier_method"
    ].startswith("default_metadata")
    assert feats["chunk_count"] == 1


def test_nim_client_uses_timeout(monkeypatch):
    from src.agents import models
    from src.core.config import settings

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-key")
    monkeypatch.setattr(settings, "NIM_ENDPOINT_POOL_ENABLED", False)
    monkeypatch.setattr(models, "OpenAI", FakeOpenAI)
    models.load_nim_client()
    assert captured.get("timeout") is not None
    assert captured.get("max_retries") == settings.NIM_SDK_MAX_RETRIES


def test_call_chat_retries_transient_connection_errors(monkeypatch):
    from src.agents import models
    from src.core.config import settings

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("Connection error.")
            return type(
                "Resp",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {"message": type("Msg", (), {"content": "ok summary"})()},
                        )()
                    ]
                },
            )()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(settings, "NIM_ENDPOINT_POOL_ENABLED", False)
    monkeypatch.setattr(models, "get_nim_client", lambda: FakeClient())
    monkeypatch.setattr(models.time, "sleep", lambda *_a, **_k: None)

    text, used = models.call_chat_with_fallback(
        ["meta/llama-3.3-70b-instruct"],
        [{"role": "user", "content": "hi"}],
        max_retries_per_model=3,
    )
    assert text == "ok summary"
    assert used == "meta/llama-3.3-70b-instruct"


def test_compile_falls_back_to_medium_when_heavy_fails(monkeypatch):
    from src.agents import models

    calls = []

    def fake_chat(model_ids, messages, **kwargs):
        calls.append(list(model_ids))
        # One de-duplicated chain — fall through by returning a lower-tier id.
        assert len(model_ids) >= 2
        return "## Summary\n\nMedium worked.", model_ids[-1]

    monkeypatch.setattr(models, "get_nim_client", lambda: object())
    monkeypatch.setattr(models, "call_chat_with_fallback", fake_chat)
    monkeypatch.setattr(models.settings, "COMPILE_MAX_INPUT_TOKENS", 100000)
    monkeypatch.setattr(models.settings, "COMPILE_BATCH_SIZE", 50)
    # Disable hedged compile so this unit test exercises the sequential ladder.
    monkeypatch.setattr(models.settings, "COMPILE_HEDGED_FALLBACK_ENABLED", False)

    out = models.run_compile_with_models(
        ["Chunk summary A about carbon routing.", "Chunk summary B about RAG."],
        {"model_usage_chars": {"light": 0, "medium": 0, "large": 0}},
        models.settings.heavy_models(),
    )
    assert "Medium worked" in out
    assert len(calls) == 1
    # Unique models only (no repeated medium/heavy primary).
    assert len(calls[0]) == len(set(calls[0]))
    assert len(calls[0]) <= 3


def test_compile_stitches_fallback_when_all_tiers_fail(monkeypatch):
    from src.agents import models

    def boom(*_a, **_k):
        raise RuntimeError("All models failed")

    monkeypatch.setattr(models, "get_nim_client", lambda: object())
    monkeypatch.setattr(models, "call_chat_with_fallback", boom)

    out = models.run_compile_with_models(
        ["Alpha finding from document.", "Beta finding from document."],
        {},
        ["meta/llama-3.3-70b-instruct"],
    )
    assert "stitched fallback" in out.lower()
    assert "Alpha finding" in out
    assert not out.startswith("Final summary generation failed")


def test_compile_skips_failed_chunk_summaries(monkeypatch):
    from src.agents import models

    captured = {}

    def fake_chat(model_ids, messages, **kwargs):
        captured["user"] = messages[-1]["content"]
        return "## Summary\nok", model_ids[0]

    monkeypatch.setattr(models, "get_nim_client", lambda: object())
    monkeypatch.setattr(models, "call_chat_with_fallback", fake_chat)
    monkeypatch.setattr(models.settings, "COMPILE_MAX_INPUT_TOKENS", 100000)

    out = models.run_compile_with_models(
        ["Good summary about scope.", "Summary generation failed.", ""],
        {},
        ["mistralai/ministral-14b-instruct-2512"],
    )
    assert out.startswith("## Summary")
    assert "Good summary about scope" in captured["user"]
    assert "Summary generation failed" not in captured["user"]
