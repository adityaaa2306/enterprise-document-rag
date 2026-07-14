import logging
import re
import time
from typing import List, Dict, Any, Optional, Tuple, Union

import httpx
import requests
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.core.config import settings

log = logging.getLogger(__name__)

# Global registry — clients/models loaded once at startup
models_registry: Dict[str, Any] = {}


_OUTER_MD_FENCE_RE = re.compile(
    r"^```(?:markdown|md|gfm)?\s*\r?\n([\s\S]*?)\r?\n```\s*$",
    re.IGNORECASE,
)
_OUTER_MD_FENCE_LOOSE_RE = re.compile(
    r"^```(?:markdown|md|gfm)?\s*\r?\n([\s\S]*?)```\s*$",
    re.IGNORECASE,
)


def strip_outer_markdown_fence(text: str) -> str:
    """Unwrap a whole-document ```markdown ... ``` wrapper if present."""
    s = (text or "").strip()
    if not s.startswith("```"):
        return text or ""
    m = _OUTER_MD_FENCE_RE.match(s) or _OUTER_MD_FENCE_LOOSE_RE.match(s)
    if m:
        return m.group(1).rstrip()
    return text or ""


class NimApiError(RuntimeError):
    """Raised when a NIM call fails due to timeout, 5xx, or connection errors."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.status_code = status_code
        self.__cause__ = cause


# ---------------------------------------------------------------------------
# NIM client bootstrap
# ---------------------------------------------------------------------------

def _nim_timeout(*, read_override: Optional[float] = None) -> httpx.Timeout:
    read = float(
        read_override
        if read_override is not None
        else (getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 90.0) or 90.0)
    )
    connect = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 15.0) or 15.0)
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

def _http_status_from_exc(exc: BaseException) -> Optional[int]:
    if isinstance(exc, NimApiError) and exc.status_code is not None:
        return int(exc.status_code)
    if isinstance(exc, APIStatusError):
        return int(getattr(exc, "status_code", 0) or 0) or None
    err = str(exc)
    for code in (429, 504, 503, 502, 500):
        if str(code) in err:
            return code
    if isinstance(exc, (APITimeoutError, httpx.TimeoutException)):
        return 408  # request timeout (synthetic)
    return None


def call_chat_with_fallback(
    model_ids: List[str],
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.5,
    max_tokens: int = 2000,
    max_retries_per_model: Optional[int] = None,
    return_timing: bool = False,
    timeout: Optional[httpx.Timeout] = None,
    call_meta: Optional[Dict[str, Any]] = None,
) -> Union[Tuple[str, Optional[str]], Tuple[str, Optional[str], Dict[str, Any]]]:
    """
    Try each model in order. On rate-limit / HTTP / empty errors, fall through
    to the next model. Returns (text, model_id_used) or raises if all fail.

    When ``return_timing=True``, uses the streaming API only to measure
    time-to-first-token vs time-to-last-token (client still gets a full
    blocking response upstream). Returns
    ``(text, model_id, {"ttft_ms", "ttlt_ms", "mode"})``.

    When ``call_meta`` dict is provided, it is filled with diagnostic fields:
    attempt log, retry_count, http_status on last failure, call_ms, model_id.

    Timeouts, connection errors, and HTTP 5xx are classified as NimApiError
    and retried on the same model before falling through.
    """
    client = get_nim_client()
    if client is None:
        raise RuntimeError("NVIDIA NIM client is not configured (missing NVIDIA_API_KEY).")

    if max_retries_per_model is None:
        max_retries_per_model = int(getattr(settings, "NIM_TRANSIENT_RETRIES", 3) or 3)
    max_retries_per_model = max(1, int(max_retries_per_model))

    last_error: Optional[Exception] = None
    req_timeout = timeout or _nim_timeout()
    t_call0 = time.perf_counter()
    attempts_log: List[Dict[str, Any]] = []
    retry_count = 0
    last_http_status: Optional[int] = None

    # De-dupe while preserving order
    seen: set = set()
    ordered_ids: List[str] = []
    for mid in model_ids or []:
        if mid and mid not in seen:
            seen.add(mid)
            ordered_ids.append(mid)

    for model_id in ordered_ids:
        for attempt in range(max_retries_per_model):
            t_attempt = time.perf_counter()
            try:
                if return_timing:
                    text, timing = _chat_completion_with_ttft(
                        client,
                        model_id=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=req_timeout,
                    )
                else:
                    completion = client.chat.completions.create(
                        model=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=req_timeout,
                    )
                    text = (completion.choices[0].message.content or "").strip()
                    timing = None
                if not text:
                    raise ValueError(f"Empty response from {model_id}")
                attempt_ms = (time.perf_counter() - t_attempt) * 1000.0
                attempts_log.append(
                    {
                        "model_id": model_id,
                        "attempt": attempt + 1,
                        "ok": True,
                        "duration_ms": round(attempt_ms, 1),
                        "http_status": 200,
                        "error": None,
                    }
                )
                log.info(f"Chat succeeded with model '{model_id}'")
                if call_meta is not None:
                    call_meta.update(
                        {
                            "model_id": model_id,
                            "retry_count": retry_count,
                            "attempt_count": len(attempts_log),
                            "http_status": None,
                            "call_ms": round((time.perf_counter() - t_call0) * 1000.0, 1),
                            "attempts": attempts_log,
                            "success": True,
                        }
                    )
                if return_timing:
                    return text, model_id, timing or {}
                return text, model_id
            except Exception as e:
                classified = _classify_nim_exception(e, model_id=model_id)
                last_error = classified if isinstance(classified, Exception) else e
                err_str = str(e)
                http_status = _http_status_from_exc(classified)
                if http_status is None:
                    http_status = _http_status_from_exc(e)
                last_http_status = http_status
                attempt_ms = (time.perf_counter() - t_attempt) * 1000.0
                attempts_log.append(
                    {
                        "model_id": model_id,
                        "attempt": attempt + 1,
                        "ok": False,
                        "duration_ms": round(attempt_ms, 1),
                        "http_status": http_status,
                        "error": f"{type(classified).__name__}: {str(classified)[:180]}",
                    }
                )
                is_rate_limit = (
                    http_status == 429
                    or "429" in err_str
                    or "rate" in err_str.lower()
                )
                transient = is_transient_nim_error(classified) or is_rate_limit

                if transient and attempt < max_retries_per_model - 1:
                    retry_count += 1
                    wait = (3 * (attempt + 1)) if is_rate_limit else (2 ** attempt)
                    log.warning(
                        "Transient NIM error on %s (%s). Retrying in %ss "
                        "(attempt %s/%s)...",
                        model_id,
                        type(classified).__name__,
                        wait,
                        attempt + 1,
                        max_retries_per_model,
                    )
                    time.sleep(wait)
                    continue

                log.warning(
                    f"Model '{model_id}' failed ({type(classified).__name__}): {classified}. "
                    f"Trying next fallback if any."
                )
                break  # next model

    if call_meta is not None:
        call_meta.update(
            {
                "model_id": None,
                "retry_count": retry_count,
                "attempt_count": len(attempts_log),
                "http_status": last_http_status,
                "call_ms": round((time.perf_counter() - t_call0) * 1000.0, 1),
                "attempts": attempts_log,
                "success": False,
                "error": str(last_error)[:300] if last_error else None,
            }
        )

    raise RuntimeError(
        f"All models failed ({ordered_ids}). Last error: {last_error}"
    ) from last_error


def _chat_completion_with_ttft(
    client: OpenAI,
    *,
    model_id: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: httpx.Timeout,
) -> Tuple[str, Dict[str, Any]]:
    """
    Stream the completion solely to separate TTFT from TTLT.
    Accumulates the full text; does not change the upstream response shape.
    Falls back to a blocking call if streaming is unsupported.
    """
    t0 = time.perf_counter()
    ttft_ms: Optional[float] = None
    parts: List[str] = []
    try:
        stream = client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            stream=True,
        )
        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content if chunk.choices else None
            except (IndexError, AttributeError):
                delta = None
            if delta:
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                parts.append(delta)
        text = "".join(parts).strip()
        ttlt_ms = (time.perf_counter() - t0) * 1000.0
        if ttft_ms is None:
            # Empty deltas until end, or provider buffered — TTFT ≈ TTLT
            ttft_ms = ttlt_ms
        return text, {
            "ttft_ms": round(ttft_ms, 3),
            "ttlt_ms": round(ttlt_ms, 3),
            "mode": "stream_measure",
        }
    except Exception as e:
        # Streaming unsupported / failed — fall back to blocking (TTFT == TTLT)
        log.warning(
            "Streaming TTFT measure failed for %s (%s); using blocking call.",
            model_id,
            type(e).__name__,
        )
        t1 = time.perf_counter()
        completion = client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        text = (completion.choices[0].message.content or "").strip()
        elapsed = (time.perf_counter() - t1) * 1000.0
        return text, {
            "ttft_ms": round(elapsed, 3),
            "ttlt_ms": round(elapsed, 3),
            "mode": "blocking_ttft_equals_ttlt",
            "stream_error": str(e)[:200],
        }


# ---------------------------------------------------------------------------
# Light / Medium / Heavy summarizers
# ---------------------------------------------------------------------------

_SUMMARIZE_SYSTEM = (
    "You are an expert summarization model. Provide a concise, factual summary "
    "in clean GitHub-Flavored Markdown (headings, bullets, bold where helpful). "
    "Do not add preamble, introduction, or conversational fluff. "
    "Never wrap the whole answer in a code fence. Never output HTML."
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
    call_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Summarize with an explicit tier (and optional model chain from the router).
    """
    if get_nim_client() is None:
        log.warning("Summarizer unavailable (NIM client not configured).")
        if call_meta is not None:
            call_meta.update(
                {
                    "success": False,
                    "error": "NIM client not configured",
                    "model_id": None,
                    "retry_count": 0,
                    "attempt_count": 0,
                    "http_status": None,
                    "call_ms": 0.0,
                    "attempts": [],
                }
            )
        return "Error: Summarizer not loaded."

    chain = model_ids or _models_for_tier(tier)
    prompt = (
        "Summarize the following text factually and concisely in GitHub-Flavored Markdown.\n"
        "Use short paragraphs and bullets when helpful. Do not wrap the whole answer in a "
        "code fence.\n\n"
        f"TEXT:\n{text}\n\nSUMMARY:"
    )
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
            call_meta=call_meta,
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
        if call_meta is not None and not call_meta.get("attempts"):
            call_meta.update(
                {
                    "success": False,
                    "error": str(e)[:300],
                    "model_id": None,
                    "retry_count": call_meta.get("retry_count", 0),
                    "attempt_count": call_meta.get("attempt_count", 0),
                    "http_status": call_meta.get("http_status"),
                    "call_ms": call_meta.get("call_ms", 0.0),
                    "attempts": call_meta.get("attempts") or [],
                }
            )
        return "Summary generation failed."


def run_light_summarizer(text: str, state: dict) -> str:
    """Light-tier chunk summarization with primary → fallback."""
    return run_tier_summarizer(text, state, tier="light")


def run_medium_summarizer(text: str, state: dict) -> str:
    """Medium-tier re-summarization."""
    return run_tier_summarizer(text, state, tier="medium")


_COMPILE_SYSTEM = (
    "You are a helpful assistant that writes polished "
    "GitHub-Flavored Markdown summaries."
)

_FAILED_SUMMARY_MARKERS = (
    "summary generation failed",
    "error: summarizer not loaded",
    "final summary generation failed",
)


def _is_usable_summary(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    return not any(m in low for m in _FAILED_SUMMARY_MARKERS)


def _normalize_compile_summaries(
    text_of_summaries: Union[str, List[str]],
) -> List[str]:
    if isinstance(text_of_summaries, list):
        raw = [str(s or "") for s in text_of_summaries]
    else:
        raw = [p.strip() for p in str(text_of_summaries or "").split("\n\n") if p.strip()]
    usable = [s.strip() for s in raw if _is_usable_summary(s)]
    return usable


def _compile_model_chains(
    primary: Optional[List[str]],
    *,
    medium_first: Optional[bool] = None,
) -> List[List[str]]:
    """
    Ordered unique model chains for compile.

    When COMPILE_MEDIUM_FIRST (default), try medium → heavy → light so Heavy
    is an exception path, not the default.
    """
    use_medium_first = (
        bool(settings.COMPILE_MEDIUM_FIRST)
        if medium_first is None
        else bool(medium_first)
    )
    chains: List[List[str]] = []
    if use_medium_first:
        ordered = (
            list(primary or []) or list(settings.medium_models()),
            list(settings.medium_models()),
            list(settings.heavy_models()),
            list(settings.light_models()),
        )
    else:
        ordered = (
            list(primary or []) or list(settings.heavy_models()),
            list(settings.medium_models()),
            list(settings.light_models()),
        )
    for chain in ordered:
        cleaned: List[str] = []
        seen: set = set()
        for mid in chain:
            if mid and mid not in seen:
                seen.add(mid)
                cleaned.append(mid)
        if cleaned and cleaned not in chains:
            chains.append(cleaned)
    return chains


def _build_compile_prompt(text_of_summaries: str, *, intermediate: bool = False) -> str:
    if intermediate:
        return f"""
You are an expert editor. Synthesize the following partial summaries into one
coherent intermediate summary in GitHub-Flavored Markdown.
Use only the information present. Do not invent facts. Never wrap the whole
answer in a code fence. Never output HTML.

PARTIAL SUMMARIES:
{text_of_summaries}

INTERMEDIATE SUMMARY:
""".strip()

    return f"""
You are an expert editor. You will be given a large collection of
small, disconnected summaries from a document.
Your job is to synthesize these summaries into a single,
coherent, well-written executive summary in GitHub-Flavored Markdown.

CRITICAL INSTRUCTIONS:
- STRICTLY use ONLY the information present in the summaries below
- DO NOT add any external information, examples, or unrelated content
- DO NOT invent, assume, or extrapolate beyond what is explicitly stated
- Synthesize the provided summaries into a cohesive narrative
- Be concise, accurate, and factual
- If the summaries are about a specific topic, stay focused on that topic only
- Use ## headings, bullet lists, and tables when they improve clarity
- Never wrap the entire answer in a triple-backtick code fence
- Never output HTML

Suggested structure:
## Summary
## Key Findings
## Details
## Metrics
(use a Markdown table if metrics appear in the source)

SUMMARIES:
{text_of_summaries}

EXECUTIVE SUMMARY:
""".strip()


def _compile_timeout() -> httpx.Timeout:
    read = float(getattr(settings, "NIM_COMPILE_TIMEOUT_SEC", 180.0) or 180.0)
    return _nim_timeout(read_override=read)


def _call_compile_llm(
    text_of_summaries: str,
    chain: List[str],
    *,
    intermediate: bool = False,
) -> Tuple[str, Optional[str]]:
    messages = [
        {"role": "system", "content": _COMPILE_SYSTEM},
        {
            "role": "user",
            "content": _build_compile_prompt(text_of_summaries, intermediate=intermediate),
        },
    ]
    # One retry only — long compile prompts must fall through quickly if a model stalls.
    return call_chat_with_fallback(
        chain,
        messages,
        temperature=0.5,
        max_tokens=1600 if intermediate else 2000,
        max_retries_per_model=1,
        timeout=_compile_timeout(),
    )


def _estimate_compile_tokens(text: str) -> int:
    try:
        from src.chunking.service import estimate_tokens

        return int(estimate_tokens(text) or 0)
    except Exception:
        return max(1, len(text or "") // 4)


def _hierarchical_compile(
    summaries: List[str],
    chains: List[List[str]],
    state: dict,
) -> str:
    """
    Batch large summary sets into intermediate compiles, then final compile.
    Falls through model chains on each step.

    Intermediate batches within a round run concurrently (COMPILE_MAX_WORKERS)
    — same inputs/outputs as sequential; lower wall-clock only.
    """
    import concurrent.futures

    batch_size = max(3, int(getattr(settings, "COMPILE_BATCH_SIZE", 8) or 8))
    max_tokens = int(getattr(settings, "COMPILE_MAX_INPUT_TOKENS", 10000) or 10000)
    compile_workers = max(1, int(getattr(settings, "COMPILE_MAX_WORKERS", 4) or 4))

    working = list(summaries)
    round_idx = 0

    def _compile_one_batch(bi: int, batch: List[str], batch_total: int) -> tuple:
        batch_text = "\n\n".join(batch)
        last_err: Optional[Exception] = None
        job_id = state.get("job_id")
        if job_id:
            try:
                from src.db import jobs as jobs_db

                jobs_db.set_progress(
                    job_id,
                    min(90.0, 82.0 + (8.0 * bi / max(batch_total, 1))),
                    f"Compiling summary batches... ({bi}/{batch_total})",
                )
            except Exception:
                pass
        log.info(
            "Compile round %s batch %s/%s (~%s tokens) models=%s",
            round_idx,
            bi,
            batch_total,
            _estimate_compile_tokens(batch_text),
            [c[0] for c in chains if c],
        )
        for chain in chains:
            try:
                text, used = _call_compile_llm(batch_text, chain, intermediate=True)
                return bi, text, used, len(batch_text), None
            except Exception as e:
                last_err = e
                log.warning("Intermediate compile batch failed on %s: %s", chain, e)
        log.error(
            "Intermediate compile dropped to raw batch after failures: %s",
            last_err,
        )
        return bi, batch_text, None, len(batch_text), last_err

    while True:
        joined = "\n\n".join(working)
        tokens = _estimate_compile_tokens(joined)
        if len(working) <= batch_size and tokens <= max_tokens:
            break
        if len(working) <= 2:
            break

        round_idx += 1
        log.info(
            "Compile hierarchical round %s: %s summaries (~%s tokens) → batches of %s",
            round_idx,
            len(working),
            tokens,
            batch_size,
        )
        batches = []
        batch_total = (len(working) + batch_size - 1) // batch_size
        for bi, i in enumerate(range(0, len(working), batch_size), start=1):
            batches.append((bi, working[i : i + batch_size]))

        results_by_bi: Dict[int, tuple] = {}
        workers = min(compile_workers, len(batches))
        if workers <= 1 or len(batches) == 1:
            for bi, batch in batches:
                bi2, text, used, nchars, err = _compile_one_batch(bi, batch, batch_total)
                results_by_bi[bi2] = (text, used, nchars)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [
                    pool.submit(_compile_one_batch, bi, batch, batch_total)
                    for bi, batch in batches
                ]
                for fut in concurrent.futures.as_completed(futs):
                    bi2, text, used, nchars, err = fut.result()
                    results_by_bi[bi2] = (text, used, nchars)

        next_level: List[str] = []
        for bi in range(1, batch_total + 1):
            text, used, nchars = results_by_bi[bi]
            next_level.append(text)
            state.setdefault("model_usage_chars", {"light": 0, "medium": 0, "large": 0})
            state["model_usage_chars"]["large"] = (
                state["model_usage_chars"].get("large", 0) + int(nchars or 0)
            )
            if used:
                state.setdefault("models_used", [])
                if used not in state["models_used"]:
                    state["models_used"].append(used)
        working = next_level

    final_text = "\n\n".join(working)
    last_error: Optional[Exception] = None
    for chain in chains:
        try:
            result, used = _call_compile_llm(final_text, chain, intermediate=False)
            state.setdefault("model_usage_chars", {"light": 0, "medium": 0, "large": 0})
            state["model_usage_chars"]["large"] = (
                state["model_usage_chars"].get("large", 0) + len(final_text)
            )
            if used:
                state.setdefault("models_used", [])
                if used not in state["models_used"]:
                    state["models_used"].append(used)
            return result
        except Exception as e:
            last_error = e
            log.warning("Final compile chain %s failed: %s", chain, e)

    raise RuntimeError(f"All compile chains failed. Last error: {last_error}") from last_error


def run_compile_with_models(
    text_of_summaries: Union[str, List[str]],
    state: dict,
    model_ids: Optional[List[str]] = None,
) -> str:
    """
    Compile chunk summaries using the router-selected chain, with:
    - hierarchical batching for large documents
    - cross-tier fallback (primary → medium → light)
    - longer NIM timeout + transient retries
    """
    if get_nim_client() is None:
        log.warning("Compile model unavailable. Falling back to medium summarizer.")
        joined = (
            "\n\n".join(text_of_summaries)
            if isinstance(text_of_summaries, list)
            else str(text_of_summaries or "")
        )
        return run_medium_summarizer(joined, state)

    summaries = _normalize_compile_summaries(text_of_summaries)
    if not summaries:
        return (
            "Unable to generate a final summary because no usable chunk summaries "
            "were produced. Please retry the upload."
        )

    chains = _compile_model_chains(model_ids)
    log.info(
        "Compile starting: summaries=%s tokens≈%s primary_models=%s",
        len(summaries),
        _estimate_compile_tokens("\n\n".join(summaries)),
        [c[0] for c in chains if c],
    )

    try:
        return strip_outer_markdown_fence(
            _hierarchical_compile(summaries, chains, state)
        )
    except Exception as e:
        log.error(f"Error in compile: {e}")
        # Last-resort: stitch usable chunk summaries so the job still has content
        stitched = "\n\n".join(f"- {s}" for s in summaries[:40])
        if stitched.strip():
            log.warning("Returning stitched chunk-summary fallback after compile failure")
            return (
                "## Summary\n\n"
                "The executive compile step could not reach NVIDIA NIM heavy models, "
                "so this is a stitched fallback from chunk summaries:\n\n"
                f"{stitched}"
            )
        return f"Final summary generation failed: {e}"


def run_large_model_compile(text_of_summaries: Union[str, List[str]], state: dict) -> str:
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
Reply in clean GitHub-Flavored Markdown (headings, bullets, tables when useful).
Never wrap the entire answer in a code fence. Never output HTML.

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
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that answers in "
                        "GitHub-Flavored Markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        if context_chunks:
            sources = [chunk.content for chunk in context_chunks]
        else:
            sources = [context_str] if context_str else []
        return strip_outer_markdown_fence(result), sources
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
