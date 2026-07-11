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
    monkeypatch.setattr(models, "OpenAI", FakeOpenAI)
    models.load_nim_client()
    assert captured.get("timeout") is not None
    assert captured.get("max_retries") == 0
