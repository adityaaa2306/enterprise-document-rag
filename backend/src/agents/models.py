import logging
import time
from typing import List, Dict, Any, Optional, Tuple

import httpx
import requests
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# Global registry — clients/models loaded once at startup
models_registry: Dict[str, Any] = {}


class NimApiError(RuntimeError):
    """Raised when a NIM call fails due to timeout, 5xx, or connection errors."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.status_code = status_code
        self.__cause__ = cause


# ---------------------------------------------------------------------------
# NIM client bootstrap
# ---------------------------------------------------------------------------

def _nim_timeout() -> httpx.Timeout:
    read = float(getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 90.0) or 90.0)
    connect = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 10.0) or 10.0)
    return httpx.Timeout(read, connect=connect)


def load_nim_client() -> None:
    """Configure the OpenAI-compatible NVIDIA NIM client with hard timeouts."""
    global models_registry
    if not settings.NVIDIA_API_KEY:
        log.error(
            "NVIDIA_API_KEY is not set. "
            "Copy backend/.env.example to backend/.env and add your key from "
            "https://build.nvidia.com/settings/api-keys"
        )
        models_registry["nim_client"] = None
        return

    try:
        timeout = _nim_timeout()
        max_retries = int(getattr(settings, "NIM_SDK_MAX_RETRIES", 0) or 0)
        log.info(
            f"Configuring NVIDIA NIM client ({settings.NVIDIA_BASE_URL}) "
            f"timeout={timeout.read}s connect={timeout.connect}s retries={max_retries}..."
        )
        models_registry["nim_client"] = OpenAI(
            api_key=settings.NVIDIA_API_KEY,
            base_url=settings.NVIDIA_BASE_URL,
            timeout=timeout,
            max_retries=max_retries,
        )
        log.info("NVIDIA NIM client configured successfully.")
    except Exception as e:
        log.error(f"Failed to configure NVIDIA NIM client: {e}")
        models_registry["nim_client"] = None


def get_nim_client() -> Optional[OpenAI]:
    return models_registry.get("nim_client")


def is_transient_nim_error(exc: BaseException) -> bool:
    """True for timeouts, connection errors, and HTTP 5xx / gateway failures."""
    if isinstance(exc, (APITimeoutError, APIConnectionError, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None) or 0
        return int(code) >= 500
    if isinstance(exc, NimApiError):
        return True
    err = str(exc).lower()
    markers = (
        "timeout",
        "timed out",
        "504",
        "502",
        "503",
        "500",
        "gateway",
        "connection",
        "temporarily unavailable",
        "service unavailable",
    )
    return any(m in err for m in markers)


def _classify_nim_exception(exc: BaseException, *, model_id: str) -> Exception:
    """Normalize SDK/network errors into NimApiError when transient."""
    if isinstance(exc, NimApiError):
        return exc
    if isinstance(exc, APITimeoutError) or isinstance(exc, httpx.TimeoutException):
        return NimApiError(
            f"NIM timeout calling {model_id} after {getattr(settings, 'NIM_HTTP_TIMEOUT_SEC', 90)}s",
            cause=exc,
        )
    if isinstance(exc, APIConnectionError):
        return NimApiError(f"NIM connection error calling {model_id}: {exc}", cause=exc)
    if isinstance(exc, APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        if code >= 500:
            return NimApiError(
                f"NIM HTTP {code} calling {model_id}: {exc}",
                status_code=code,
                cause=exc,
            )
    if is_transient_nim_error(exc):
        return NimApiError(f"NIM transient failure calling {model_id}: {exc}", cause=exc)
    return exc if isinstance(exc, Exception) else RuntimeError(str(exc))


# ---------------------------------------------------------------------------
# Within-tier chat fallback
# ---------------------------------------------------------------------------

def call_chat_with_fallback(
    model_ids: List[str],
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.5,
    max_tokens: int = 2000,
    max_retries_per_model: int = 2,
) -> Tuple[str, Optional[str]]:
    """
    Try each model in order. On rate-limit / HTTP / empty errors, fall through
    to the next model. Returns (text, model_id_used) or raises if all fail.

    Timeouts, connection errors, and HTTP 5xx are classified as NimApiError
    so callers can soft-fail optional steps or hard-fail essential ones.
    """
    client = get_nim_client()
    if client is None:
        raise RuntimeError("NVIDIA NIM client is not configured (missing NVIDIA_API_KEY).")

    last_error: Optional[Exception] = None
    timeout = _nim_timeout()

    for model_id in model_ids:
        for attempt in range(max_retries_per_model):
            try:
                completion = client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                text = (completion.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError(f"Empty response from {model_id}")
                log.info(f"Chat succeeded with model '{model_id}'")
                return text, model_id
            except Exception as e:
                classified = _classify_nim_exception(e, model_id=model_id)
                last_error = classified if isinstance(classified, Exception) else e
                err_str = str(e)
                is_rate_limit = "429" in err_str or "rate" in err_str.lower()
                if is_rate_limit and attempt < max_retries_per_model - 1:
                    wait = 3 * (attempt + 1)
                    log.warning(
                        f"Rate limit on {model_id}. Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{max_retries_per_model})..."
                    )
                    time.sleep(wait)
                    continue
                log.warning(
                    f"Model '{model_id}' failed ({type(classified).__name__}): {classified}. "
                    f"Trying next fallback if any."
                )
                break  # next model

    raise RuntimeError(
        f"All models failed ({model_ids}). Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Light / Medium / Heavy summarizers
# ---------------------------------------------------------------------------

_SUMMARIZE_SYSTEM = (
    "You are an expert summarization model. Provide a concise, factual summary. "
    "Do not add preamble, introduction, or conversational fluff."
)


def _usage_key(tier: str) -> str:
    return {"light": "light", "medium": "medium", "heavy": "large"}.get(tier, "light")


def _models_for_tier(tier: str) -> List[str]:
    t = (tier or "light").lower()
    if t == "medium":
        return settings.medium_models()
    if t == "heavy":
        return settings.heavy_models()
    return settings.light_models()


def run_tier_summarizer(
    text: str,
    state: dict,
    tier: str = "light",
    model_ids: Optional[List[str]] = None,
) -> str:
    """
    Summarize with an explicit tier (and optional model chain from the router).
    """
    if get_nim_client() is None:
        log.warning("Summarizer unavailable (NIM client not configured).")
        return "Error: Summarizer not loaded."

    chain = model_ids or _models_for_tier(tier)
    prompt = f"Summarize the following text factually and concisely.\n\nTEXT:\n{text}\n\nSUMMARY:"
    max_tokens = {"light": 300, "medium": 500, "heavy": 800}.get((tier or "light").lower(), 300)
    try:
        result, used = call_chat_with_fallback(
            chain,
            [
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        key = _usage_key(tier)
        state.setdefault("model_usage_chars", {"light": 0, "medium": 0, "large": 0})
        state["model_usage_chars"][key] = state["model_usage_chars"].get(key, 0) + len(text)
        if used:
            state.setdefault("models_used", [])
            if used not in state["models_used"]:
                state["models_used"].append(used)
        return result
    except Exception as e:
        log.error(f"Error in {tier} summarizer: {e}")
        return "Summary generation failed."


def run_light_summarizer(text: str, state: dict) -> str:
    """Light-tier chunk summarization with primary → fallback."""
    return run_tier_summarizer(text, state, tier="light")


def run_medium_summarizer(text: str, state: dict) -> str:
    """Medium-tier re-summarization."""
    return run_tier_summarizer(text, state, tier="medium")


def run_compile_with_models(
    text_of_summaries: str,
    state: dict,
    model_ids: Optional[List[str]] = None,
) -> str:
    """Compile chunk summaries using router-selected compile chain."""
    if get_nim_client() is None:
        log.warning("Compile model unavailable. Falling back to medium summarizer.")
        return run_medium_summarizer(text_of_summaries, state)

    chain = model_ids or settings.heavy_models()
    prompt = f"""
You are an expert editor. You will be given a large collection of
small, disconnected summaries from a document.
Your job is to synthesize these summaries into a single,
coherent, well-written executive summary.

CRITICAL INSTRUCTIONS:
- STRICTLY use ONLY the information present in the summaries below
- DO NOT add any external information, examples, or unrelated content
- DO NOT invent, assume, or extrapolate beyond what is explicitly stated
- Synthesize the provided summaries into a cohesive narrative
- Be concise, accurate, and factual
- If the summaries are about a specific topic, stay focused on that topic only

SUMMARIES:
{text_of_summaries}

EXECUTIVE SUMMARY:
"""
    try:
        result, used = call_chat_with_fallback(
            chain,
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=2000,
        )
        state.setdefault("model_usage_chars", {"light": 0, "medium": 0, "large": 0})
        state["model_usage_chars"]["large"] = state["model_usage_chars"].get("large", 0) + len(
            text_of_summaries
        )
        if used:
            state.setdefault("models_used", [])
            if used not in state["models_used"]:
                state["models_used"].append(used)
        return result
    except Exception as e:
        log.error(f"Error in compile: {e}")
        return f"Final summary generation failed: {e}"


def run_large_model_compile(text_of_summaries: str, state: dict) -> str:
    """Heavy-tier: compile chunk summaries into one executive summary."""
    return run_compile_with_models(text_of_summaries, state, settings.heavy_models())


def run_large_model_rag(
    query: str,
    context_chunks: Optional[List] = None,
    context_str: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Heavy-tier RAG answer generation."""
    if get_nim_client() is None:
        log.warning("Heavy model unavailable. Cannot answer RAG query.")
        return (
            "Error: RAG model not loaded. Please ensure your NVIDIA_API_KEY is set.",
            [],
        )

    if context_str is None:
        context_chunks = context_chunks or []
        context_str = "\n\n---\n\n".join([chunk.content for chunk in context_chunks])
    prompt = f"""
You are an expert Q&A assistant. Answer the user's query *only* based on
the provided context. Be concise and factual.

CONTEXT:
{context_str}

QUERY:
{query}

ANSWER:
"""
    try:
        result, _ = call_chat_with_fallback(
            settings.heavy_models(),
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        if context_chunks:
            sources = [chunk.content for chunk in context_chunks]
        else:
            sources = [context_str] if context_str else []
        return result, sources
    except Exception as e:
        log.error(f"Error in RAG model: {e}")
        return "Failed to generate answer.", []


# ---------------------------------------------------------------------------
# Embeddings (NIM)
# ---------------------------------------------------------------------------

def embed_texts(texts: List[str], *, input_type: str = "passage") -> List[List[float]]:
    """
    Embed one or more texts via NVIDIA NIM embeddings API.
    Returns a list of embedding vectors (same order as input).

    ``input_type`` is required for asymmetric NIM models (e.g. nemotron-embed):
    use ``passage`` for documents/chunks and ``query`` for search queries.
    """
    client = get_nim_client()
    if client is None:
        raise RuntimeError("NVIDIA NIM client is not configured (missing NVIDIA_API_KEY).")

    if not texts:
        return []

    model_id = settings.EMBEDDING_MODEL
    use_cache = bool(getattr(settings, "ENABLE_EMBEDDING_CACHE", True))
    itype = (input_type or "passage").strip() or "passage"

    if use_cache:
        from src.memory import embedding_cache

        cached, miss_indices = embedding_cache.get_many(model_id, texts, input_type=itype)
        if not miss_indices:
            return [v for v in cached]  # type: ignore[misc]

        to_embed = [texts[i] for i in miss_indices]
        fresh = _embed_batch_nim(client, model_id, to_embed, input_type=itype)
        embedding_cache.put_many(model_id, to_embed, fresh, input_type=itype)
        out: List[List[float]] = []
        fresh_iter = iter(fresh)
        for i, existing in enumerate(cached):
            if existing is not None:
                out.append(existing)
            else:
                out.append(next(fresh_iter))
        return out

    return _embed_batch_nim(client, model_id, texts, input_type=itype)


def _embed_batch_nim(
    client: OpenAI,
    model_id: str,
    texts: List[str],
    *,
    input_type: str = "passage",
) -> List[List[float]]:
    """Call NIM embeddings API in batches; preserve input order. Raises NimApiError on transient failures."""
    if not texts:
        return []
    batch_size = 32
    all_embeddings: List[List[float]] = []
    timeout = _nim_timeout()
    itype = (input_type or "passage").strip() or "passage"
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            response = client.embeddings.create(
                model=model_id,
                input=batch,
                timeout=timeout,
                extra_body={"input_type": itype},
            )
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        except Exception as e:
            raise _classify_nim_exception(e, model_id=model_id) from e
    return all_embeddings


def get_embedding_model():
    """
    Compatibility shim for storage.py.
    Returns True-ish if NIM embeddings are available, else None.
    Callers should use embed_texts() for actual vectors.
    """
    return get_nim_client()


# ---------------------------------------------------------------------------
# Reranking (NIM /v1/ranking)
# ---------------------------------------------------------------------------

def rerank(query: str, passages: List[str], top_k: int) -> List[str]:
    """
    Rerank passages against a query using NVIDIA NIM ranking API.
    Returns the top_k passages in relevance order.
    On failure, returns the original passages truncated to top_k.
    """
    if not passages:
        return []

    top_k = max(1, min(top_k, len(passages)))

    if get_nim_client() is None or not settings.NVIDIA_API_KEY:
        log.warning("Reranker unavailable; returning first top_k passages.")
        return passages[:top_k]

    url = settings.NVIDIA_BASE_URL.rstrip("/") + "/ranking"
    payload = {
        "model": settings.RERANK_MODEL,
        "query": {"text": query},
        "passages": [{"text": p} for p in passages],
        "truncate": "END",
    }
    headers = {
        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    rerank_timeout = min(60.0, float(getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 90.0) or 90.0))
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=rerank_timeout)
        resp.raise_for_status()
        data = resp.json()
        rankings = data.get("rankings") or data.get("results") or []

        # Expected: [{"index": int, "logit": float}, ...] already sorted or not
        if not rankings:
            log.warning("Rerank returned empty rankings; using original order.")
            return passages[:top_k]

        # Sort by logit descending if present
        def _score(item: dict) -> float:
            return float(item.get("logit", item.get("score", 0.0)))

        ordered = sorted(rankings, key=_score, reverse=True)
        result: List[str] = []
        for item in ordered:
            idx = int(item["index"])
            if 0 <= idx < len(passages):
                result.append(passages[idx])
            if len(result) >= top_k:
                break

        # Fill if somehow short
        if len(result) < top_k:
            for p in passages:
                if p not in result:
                    result.append(p)
                if len(result) >= top_k:
                    break

        log.info(f"Reranked {len(passages)} passages → top {len(result)}")
        return result
    except Exception as e:
        log.error(f"Rerank failed: {e}. Falling back to original order.")
        return passages[:top_k]


# ---------------------------------------------------------------------------
# Startup loader
# ---------------------------------------------------------------------------

def load_all_models():
    """
    Called once on API startup. Configures the NVIDIA NIM OpenAI-compatible client.
    No local Hugging Face / NLI model downloads.
    """
    log.info("--- Loading NVIDIA NIM stack... ---")
    load_nim_client()
    if get_nim_client():
        log.info(
            "NIM models ready: "
            f"light={settings.light_models()}, "
            f"medium={settings.medium_models()}, "
            f"heavy={settings.heavy_models()}, "
            f"embed={settings.EMBEDDING_MODEL}, "
            f"rerank={settings.RERANK_MODEL}"
        )
    else:
        log.warning("NIM client not ready — set NVIDIA_API_KEY in backend/.env")
    log.info("--- Model loading complete. ---")
