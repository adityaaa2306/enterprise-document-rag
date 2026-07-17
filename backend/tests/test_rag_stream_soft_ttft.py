"""Interactive RAG stream must fail over on soft-TTFT, not wait full HTTP timeout."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Iterator, List

import pytest

from src.agents import models as models_mod
from src.agents.models import NimApiError


class _FakeDelta:
    def __init__(self, content: str | None):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None):
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content: str | None):
        self.choices = [_FakeChoice(content)]


class _HungStream:
    """Never yields — simulates a hung NIM socket with zero chunks."""

    def __iter__(self) -> Iterator[Any]:
        time.sleep(30)
        if False:  # pragma: no cover
            yield _FakeChunk("x")


class _OkStream:
    def __iter__(self) -> Iterator[_FakeChunk]:
        yield _FakeChunk("Hello")
        yield _FakeChunk(" world")


class _FakeCompletions:
    def __init__(self, behavior: dict[str, Any]):
        self.behavior = behavior
        self.calls: List[str] = []

    def create(self, **kwargs: Any):
        model = kwargs["model"]
        self.calls.append(model)
        mode = self.behavior.get(model, "ok")
        if mode == "hang":
            return _HungStream()
        if mode == "empty":
            return iter(())
        return _OkStream()


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = _FakeChat(completions)


@pytest.fixture
def soft_ttft_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(models_mod.settings, "NIM_TRANSIENT_RETRIES", 1)
    monkeypatch.setattr(models_mod.settings, "NIM_RAG_SOFT_TTFT_TIMEOUT_SEC", 0.35)
    monkeypatch.setattr(models_mod.settings, "NIM_SOFT_TTFT_TIMEOUT_SEC", 0.35)
    monkeypatch.setattr(models_mod.settings, "NIM_HTTP_TIMEOUT_SEC", 75.0)


def test_stream_soft_ttft_fails_over_to_next_model(soft_ttft_settings, monkeypatch):
    comps = _FakeCompletions({"primary-slow": "hang", "fallback-fast": "ok"})
    monkeypatch.setattr(models_mod, "get_nim_client", lambda: _FakeClient(comps))

    tokens: List[str] = []
    done = None
    t0 = time.perf_counter()
    for kind, payload in models_mod.iter_chat_stream_with_fallback(
        ["primary-slow", "fallback-fast"],
        [{"role": "user", "content": "hi"}],
        max_tokens=32,
    ):
        if kind == "token":
            tokens.append(payload)
        elif kind == "done":
            done = payload
    elapsed = time.perf_counter() - t0

    assert "".join(tokens) == "Hello world"
    assert done is not None
    assert done["model_id"] == "fallback-fast"
    assert comps.calls == ["primary-slow", "fallback-fast"]
    # Must not wait anything close to the 75s HTTP timeout.
    assert elapsed < 5.0


def test_single_model_stream_raises_soft_ttft(soft_ttft_settings, monkeypatch):
    comps = _FakeCompletions({"only": "hang"})
    client = _FakeClient(comps)
    t0 = time.perf_counter()
    with pytest.raises(NimApiError, match="soft_ttft"):
        list(
            models_mod._iter_single_model_stream(
                client,
                model_id="only",
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=16,
                timeout=SimpleNamespace(read=75.0, connect=5.0),
                soft_ttft_timeout_sec=0.3,
            )
        )
    assert time.perf_counter() - t0 < 2.0
