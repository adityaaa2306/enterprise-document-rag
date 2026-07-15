"""Ollama unavailable → NIM fallback chain (no local daemon required)."""
from __future__ import annotations


def test_ollama_prefix_falls_through_to_nim(monkeypatch):
    from src.agents import models
    from src.core.config import settings

    object.__setattr__(settings, "LLM_PROVIDER", "ollama")
    calls = {"ollama": 0, "nim": 0}

    class FakeOllama:
        name = "ollama"

        def chat(self, model_id, messages, **kwargs):
            calls["ollama"] += 1
            raise ConnectionError("ollama down")

    def fake_resolve(mid):
        return FakeOllama()

    def fake_nim_path(*a, **k):
        # Intercept by making get_nim_client return a stub that succeeds
        pass

    monkeypatch.setattr(
        "src.core.llm_providers.resolve_provider_for_model", fake_resolve
    )

    # Patch the NIM client chat completions path used after ollama fail
    class Resp:
        class Choice:
            class Msg:
                content = "ok from nim"

            message = Msg()

        choices = [Choice()]
        usage = None

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls["nim"] += 1
                    return Resp()

    monkeypatch.setattr(models, "get_nim_client", lambda: FakeClient())
    monkeypatch.setattr(settings, "NIM_ENDPOINT_POOL_ENABLED", False)

    text, used = models.call_chat_with_fallback(
        ["ollama/llama3.2", "meta/llama-3.1-8b-instruct"],
        [{"role": "user", "content": "hi"}],
        max_retries_per_model=1,
    )
    assert calls["ollama"] >= 1
    assert calls["nim"] >= 1
    assert "ok" in text.lower() or used
