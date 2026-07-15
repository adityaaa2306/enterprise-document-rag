"""
Provider-agnostic LLM adapters (NIM / OpenAI-compatible / Ollama).

Workers call ``get_chat_provider()`` — adding a provider is a new adapter class,
not a new worker code path. Light/Medium/Heavy tier lists stay in settings.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import settings

log = logging.getLogger(__name__)


class ChatProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.5,
        max_tokens: int = 2000,
        timeout: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Return (text, meta)."""


class OpenAICompatibleProvider(ChatProvider):
    """NVIDIA NIM and any OpenAI-compatible endpoint."""

    name = "openai_compatible"

    def chat(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.5,
        max_tokens: int = 2000,
        timeout: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        from src.agents import models

        meta: Dict[str, Any] = {}
        text, used = models.call_chat_with_fallback(
            [model_id],
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries_per_model=1,
            call_meta=meta,
        )
        meta["provider"] = self.name
        meta["model_id"] = used or model_id
        return text, meta


class OllamaProvider(ChatProvider):
    """Local Ollama HTTP API (http://localhost:11434)."""

    name = "ollama"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (
            base_url
            or getattr(settings, "OLLAMA_BASE_URL", None)
            or "http://127.0.0.1:11434"
        ).rstrip("/")

    def chat(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.5,
        max_tokens: int = 2000,
        timeout: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        import httpx

        # Allow "ollama/llama3" or bare model names
        mid = model_id.split("/", 1)[-1] if model_id.startswith("ollama/") else model_id
        payload = {
            "model": mid,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        to = float(timeout or getattr(settings, "OLLAMA_TIMEOUT_SEC", 120) or 120)
        with httpx.Client(timeout=to) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = ((data.get("message") or {}).get("content") or "").strip()
        if not text:
            raise RuntimeError(f"Empty Ollama response from {mid}")
        return text, {
            "provider": self.name,
            "model_id": mid,
            "success": True,
        }


_PROVIDERS: Dict[str, ChatProvider] = {}


def get_chat_provider(name: Optional[str] = None) -> ChatProvider:
    key = (name or getattr(settings, "LLM_PROVIDER", None) or "openai_compatible").lower()
    if key in ("nim", "nvidia", "openai", "openai_compatible"):
        key = "openai_compatible"
    if key not in _PROVIDERS:
        if key == "ollama":
            _PROVIDERS[key] = OllamaProvider()
        else:
            _PROVIDERS[key] = OpenAICompatibleProvider()
    return _PROVIDERS[key]


def resolve_provider_for_model(model_id: str) -> ChatProvider:
    """Route ollama/* models to Ollama; everything else to OpenAI-compatible."""
    if (model_id or "").startswith("ollama/") or getattr(settings, "LLM_PROVIDER", "") == "ollama":
        return get_chat_provider("ollama")
    return get_chat_provider("openai_compatible")
