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


try:
    from openai import RateLimitError as _OpenAIRateLimitError
except ImportError:  # pragma: no cover
    _OpenAIRateLimitError = ()  # type: ignore


# ---------------------------------------------------------------------------
# NIM client bootstrap
# ---------------------------------------------------------------------------

def _nim_timeout(*, read_override: Optional[float] = None) -> httpx.Timeout:
    """HTTP timeout always capped strictly below MAP_CHUNK_HARD_TIMEOUT_SEC."""
    map_wall = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    default_read = float(getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 75.0) or 75.0)
    read = float(read_override if read_override is not None else default_read)
    # Hung sockets must abort before the node wrapper wall.
    read = min(read, max(1.0, map_wall - 1.0))
    connect = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 15.0) or 15.0)
    connect = min(connect, max(1.0, read))
    return httpx.Timeout(read, connect=connect)


def load_nim_client() -> None:
    """Configure NVIDIA NIM client(s) — multi-endpoint pool when enabled."""
    global models_registry
    if not settings.NVIDIA_API_KEY and not (
        getattr(settings, "NIM_API_KEYS", None) or ""
    ).strip():
        log.error(
            "NVIDIA_API_KEY is not set. "
            "Copy backend/.env.example to backend/.env and add your key from "
            "https://build.nvidia.com/settings/api-keys"
        )
        models_registry["nim_client"] = None
        return

    try:
        if bool(getattr(settings, "NIM_ENDPOINT_POOL_ENABLED", True)):
            from src.agents import nim_endpoint_pool as pool

            pool.load_endpoint_pool()
            models_registry["nim_client"] = pool.primary_client()
            log.info(
                "NVIDIA NIM pool ready endpoints=%s strategy=%s",
                pool.endpoint_count(),
                getattr(settings, "NIM_ENDPOINT_STRATEGY", "least_load"),
            )
        else:
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
    """Return a NIM client (primary / any from pool). Prefer acquire via call path."""
    client = models_registry.get("nim_client")
    if client is not None:
        return client
    if bool(getattr(settings, "NIM_ENDPOINT_POOL_ENABLED", True)):
        try:
            from src.agents import nim_endpoint_pool as pool

            pool.ensure_pool_loaded()
            client = pool.primary_client()
            models_registry["nim_client"] = client
            return client
        except Exception:
            return None
    return None


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
    # 429 must surface as RateLimitBackpressure — not a hung-socket path.
    from src.core.nim_rate_limit import RateLimitBackpressure, is_rate_limit_error

    if is_rate_limit_error(exc) or (
        _OpenAIRateLimitError and isinstance(exc, _OpenAIRateLimitError)
    ):
        retry_after = None
        headers = getattr(exc, "headers", None) or getattr(
            getattr(exc, "response", None), "headers", None
        )
        if headers:
            try:
                ra = headers.get("retry-after") or headers.get("Retry-After")
                if ra is not None:
                    retry_after = float(ra)
            except Exception:
                pass
        return RateLimitBackpressure(
            f"NIM rate limit calling {model_id}: {exc}",
            retry_after_sec=retry_after,
            status_code=429,
        )
    if isinstance(exc, APITimeoutError) or isinstance(exc, httpx.TimeoutException):
        return NimApiError(
            f"NIM timeout calling {model_id} after {getattr(settings, 'NIM_HTTP_TIMEOUT_SEC', 90)}s",
            cause=exc,
        )
    if isinstance(exc, APIConnectionError):
        return NimApiError(f"NIM connection error calling {model_id}: {exc}", cause=exc)
    if isinstance(exc, APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        if code == 429:
            return RateLimitBackpressure(
                f"NIM HTTP 429 calling {model_id}: {exc}",
                status_code=429,
            )
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
    deadline_mono: Optional[float] = None,
) -> Union[Tuple[str, Optional[str]], Tuple[str, Optional[str], Dict[str, Any]]]:
    """
    Try each model in order under an optional shared ``deadline_mono`` wall.

    When ``CHAIN_SLICE_ENABLED``, each model receives an explicit time slice of
    the remaining wall so the primary cannot starve fallbacks.
    """
    from src.core.chain_time_budget import (
        get_reliability_tracker,
        log_slice_report,
        plan_chain_slices,
    )

    # De-dupe while preserving order
    seen: set = set()
    ordered_ids: List[str] = []
    for mid in model_ids or []:
        if mid and mid not in seen:
            seen.add(mid)
            ordered_ids.append(mid)
    if not ordered_ids:
        raise RuntimeError("No models provided to call_chat_with_fallback")

    role = "compile" if (call_meta or {}).get("phase") == "compile" else "map"
    if call_meta and call_meta.get("endpoint_role"):
        role = str(call_meta.get("endpoint_role"))

    slice_enabled = bool(getattr(settings, "CHAIN_SLICE_ENABLED", True))
    if (not slice_enabled) or len(ordered_ids) == 1:
        return _call_chat_with_fallback_unsliced(
            ordered_ids,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries_per_model=max_retries_per_model,
            return_timing=return_timing,
            timeout=timeout,
            call_meta=call_meta,
            deadline_mono=deadline_mono,
        )

    # Remaining wall for the whole chain
    if deadline_mono is not None:
        wall_sec = max(0.5, float(deadline_mono) - time.monotonic())
    else:
        # No outer deadline — derive a sensible chain wall from role defaults.
        if role == "compile":
            wall_sec = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
        else:
            wall_sec = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
        deadline_mono = time.monotonic() + wall_sec

    ordered_ids, slices, report = plan_chain_slices(
        ordered_ids, role=role, wall_sec=wall_sec
    )
    if call_meta is not None:
        call_meta["chain_slices"] = report.to_dict()
        call_meta["chain_slice_plan"] = [
            {"model_id": a.model_id, "allocated_sec": a.allocated_sec}
            for a in report.attempts
        ]

    tracker = get_reliability_tracker()
    last_error: Optional[Exception] = None
    import concurrent.futures

    for i, model_id in enumerate(ordered_ids):
        slice_sec = float(slices[i] if i < len(slices) else slices[-1])
        # Never let a model run past the shared wall.
        model_deadline = min(float(deadline_mono), time.monotonic() + slice_sec)
        remaining = model_deadline - time.monotonic()
        if remaining < 0.35:
            att = report.attempts[i]
            att.outcome = "skipped"
            att.used_sec = 0.0
            att.error = f"insufficient_slice_remaining={remaining:.2f}s"
            log.warning(
                "CHAIN_SLICE skip model=%s remaining=%.2fs (starvation prevented upstream)",
                model_id,
                remaining,
            )
            continue

        att = report.attempts[i]
        t0 = time.monotonic()
        meta_i: Dict[str, Any] = dict(call_meta or {})
        meta_i["phase"] = (call_meta or {}).get("phase") or role
        meta_i["endpoint_role"] = role
        meta_i["task_id"] = (call_meta or {}).get("task_id")
        meta_i["chain_position"] = i
        meta_i["slice_allocated_sec"] = slice_sec

        def _invoke() -> Any:
            return _call_chat_with_fallback_unsliced(
                [model_id],
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries_per_model=max_retries_per_model,
                return_timing=return_timing,
                timeout=timeout,
                call_meta=meta_i,
                deadline_mono=model_deadline,
            )

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(_invoke)
        try:
            # Hard cut at slice boundary — primary cannot burn the whole wall.
            out = fut.result(timeout=max(0.3, remaining))
            used = time.monotonic() - t0
            att.used_sec = used
            att.outcome = "success"
            tracker.record(model_id, ok=True, timeout=False)
            if call_meta is not None:
                call_meta.update({k: v for k, v in meta_i.items() if k != "attempts"})
                call_meta["attempts"] = list(call_meta.get("attempts") or []) + list(
                    meta_i.get("attempts") or []
                )
                call_meta["chain_slices"] = report.to_dict()
                call_meta["model_reliability"] = tracker.stats(model_id)
            log.info(
                "CHAIN_SLICE model=%s pos=%s alloc=%.1fs used=%.1fs outcome=success",
                model_id,
                i,
                slice_sec,
                used,
            )
            log_slice_report(report)
            return out
        except concurrent.futures.TimeoutError as e:
            used = time.monotonic() - t0
            att.used_sec = used
            att.outcome = "timeout_slice"
            att.error = f"slice_timeout after {used:.1f}s (alloc={slice_sec:.1f}s)"
            tracker.record(model_id, ok=False, timeout=True)
            last_error = NimApiError(
                f"Model slice timeout after {used:.1f}s "
                f"(alloc={slice_sec:.1f}s model={model_id})"
            )
            log.warning(
                "CHAIN_SLICE model=%s pos=%s alloc=%.1fs used=%.1fs outcome=timeout_slice "
                "— falling through to next fallback",
                model_id,
                i,
                slice_sec,
                used,
            )
            if call_meta is not None:
                call_meta.setdefault("attempts", [])
                call_meta["attempts"] = list(call_meta.get("attempts") or []) + [
                    {
                        "model_id": model_id,
                        "ok": False,
                        "duration_ms": round(used * 1000.0, 1),
                        "error": att.error,
                        "slice_timeout": True,
                        "allocated_sec": slice_sec,
                    }
                ]
        except Exception as e:
            used = time.monotonic() - t0
            att.used_sec = used
            err_l = str(e).lower()
            is_to = "timeout" in err_l or "deadline" in err_l
            att.outcome = "timeout_slice" if is_to else "error"
            att.error = f"{type(e).__name__}: {str(e)[:160]}"
            tracker.record(model_id, ok=False, timeout=is_to, error=not is_to)
            last_error = e if isinstance(e, Exception) else RuntimeError(str(e))
            log.warning(
                "CHAIN_SLICE model=%s pos=%s alloc=%.1fs used=%.1fs outcome=%s err=%s",
                model_id,
                i,
                slice_sec,
                used,
                att.outcome,
                att.error,
            )
            if call_meta is not None:
                call_meta["attempts"] = list(call_meta.get("attempts") or []) + list(
                    meta_i.get("attempts") or []
                ) + [
                    {
                        "model_id": model_id,
                        "ok": False,
                        "duration_ms": round(used * 1000.0, 1),
                        "error": att.error,
                        "allocated_sec": slice_sec,
                    }
                ]
        finally:
            _shutdown_executor_nowait(pool, fut)

    if call_meta is not None:
        call_meta["chain_slices"] = report.to_dict()
        call_meta["success"] = False
        call_meta["error"] = str(last_error)[:300] if last_error else "all_slices_failed"
    log_slice_report(report)
    raise RuntimeError(
        f"All models failed under chain slices ({ordered_ids}). Last error: {last_error}"
    ) from last_error


def _call_chat_with_fallback_unsliced(
    model_ids: List[str],
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.5,
    max_tokens: int = 2000,
    max_retries_per_model: Optional[int] = None,
    return_timing: bool = False,
    timeout: Optional[httpx.Timeout] = None,
    call_meta: Optional[Dict[str, Any]] = None,
    deadline_mono: Optional[float] = None,
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

    When ``deadline_mono`` is set (``time.monotonic()`` deadline), the shared
    budget covers the whole fallback chain — further models are skipped once
    the deadline is reached.

    Timeouts, connection errors, and HTTP 5xx are classified as NimApiError
    and retried on the same model before falling through.

    When the endpoint pool is enabled, each attempt uses the healthiest NIM
    endpoint; failures cool that endpoint and the next try picks another.
    """
    use_pool = bool(getattr(settings, "NIM_ENDPOINT_POOL_ENABLED", True))
    pool_mod = None
    if use_pool:
        try:
            from src.agents import nim_endpoint_pool as pool_mod
        except Exception:
            pool_mod = None
            use_pool = False

    lease = None
    role = "compile" if (call_meta or {}).get("phase") == "compile" else "map"
    if call_meta and call_meta.get("endpoint_role"):
        role = str(call_meta.get("endpoint_role"))
    task_id = str((call_meta or {}).get("task_id") or "-")
    exclude_endpoints: set = set()
    acquire_timeout = float(
        getattr(settings, "NIM_ENDPOINT_ACQUIRE_TIMEOUT_SEC", 120.0) or 120.0
    )
    # Never wait for a lease past the scheduler deadline — that was orphaning
    # capacity while the outer hard-timeout abandoned the worker thread.
    if deadline_mono is not None:
        acquire_timeout = min(
            acquire_timeout, max(0.5, float(deadline_mono) - time.monotonic() - 0.25)
        )
    soft_ttft = float(getattr(settings, "NIM_SOFT_TTFT_TIMEOUT_SEC", 45.0) or 0.0)
    # Soft TTFT applies to map/embed paths; compile uses its own shorter wall.
    use_soft_ttft = soft_ttft > 0 and role != "compile"
    # Measure TTFT whenever soft timeout is active (stream + cancel).
    measure_ttft = bool(return_timing or use_soft_ttft)

    def _deadline_left() -> float:
        if deadline_mono is None:
            return 1e9
        return float(deadline_mono) - time.monotonic()

    def _raise_if_deadline(where: str) -> None:
        left = _deadline_left()
        if left <= 0.25:
            raise NimApiError(
                f"Shared call deadline exhausted at {where} (remaining={left:.2f}s)"
            )

    def _acquire_client():
        nonlocal lease
        _raise_if_deadline("acquire_endpoint")
        if use_pool and pool_mod is not None:
            acq_to = acquire_timeout
            if deadline_mono is not None:
                acq_to = min(acq_to, max(0.5, _deadline_left() - 0.25))
            lease = pool_mod.acquire_endpoint(
                role=role,
                exclude_ids=exclude_endpoints or None,
                block=True,
                timeout=acq_to,
            )
            if lease is None and exclude_endpoints:
                # All preferred endpoints busy/cooling — allow any with capacity
                lease = pool_mod.acquire_endpoint(
                    role=role,
                    block=True,
                    timeout=min(30.0, acq_to, max(0.5, _deadline_left() - 0.25)),
                )
            if lease is not None:
                log.info(
                    "TASK_LIFECYCLE phase=ENDPOINT_SELECTED task=%s endpoint=%s role=%s",
                    task_id,
                    lease.endpoint_id,
                    role,
                )
            return lease.client if lease else get_nim_client()
        return get_nim_client()

    client = _acquire_client()
    if client is None:
        raise RuntimeError("NVIDIA NIM client is not configured (missing NVIDIA_API_KEY).")

    if max_retries_per_model is None:
        max_retries_per_model = int(getattr(settings, "NIM_TRANSIENT_RETRIES", 1) or 1)
    max_retries_per_model = max(1, int(max_retries_per_model))
    # Extra same-model tries across different endpoints before model fallback.
    endpoint_retries = max(
        1, int(getattr(settings, "NIM_ENDPOINT_RETRIES_PER_MODEL", 2) or 2)
    )

    last_error: Optional[Exception] = None
    hard_read = float(
        getattr(settings, "NIM_HARD_TIMEOUT_SEC", None)
        or getattr(settings, "NIM_HTTP_TIMEOUT_SEC", 75.0)
        or 75.0
    )
    map_wall = float(getattr(settings, "MAP_CHUNK_HARD_TIMEOUT_SEC", 90.0) or 90.0)
    hard_read = min(hard_read, max(1.0, map_wall - 1.0))
    # Cap hard read to remaining deadline so HTTP aborts inside the slice.
    if deadline_mono is not None:
        hard_read = min(hard_read, max(1.0, float(deadline_mono) - time.monotonic() - 0.25))
    base_timeout = timeout or _nim_timeout(read_override=hard_read)
    t_call0 = time.perf_counter()
    attempts_log: List[Dict[str, Any]] = []
    retry_count = 0
    last_http_status: Optional[int] = None
    connect_cap = float(getattr(settings, "NIM_CONNECT_TIMEOUT_SEC", 15.0) or 15.0)

    # De-dupe while preserving order
    seen: set = set()
    ordered_ids: List[str] = []
    for mid in model_ids or []:
        if mid and mid not in seen:
            seen.add(mid)
            ordered_ids.append(mid)

    for model_id in ordered_ids:
        # Provider routing: ollama/* always uses Ollama adapter. Global
        # LLM_PROVIDER=ollama only remaps non-NIM model ids — NIM-looking
        # ids (meta/, mistralai/, …) still use the NIM HTTP client so
        # fallback chains can leave Ollama when it is down/slow.
        mid_s = str(model_id)
        use_alt_provider = mid_s.startswith("ollama/")
        if (
            not use_alt_provider
            and str(getattr(settings, "LLM_PROVIDER", "") or "").lower() == "ollama"
        ):
            nim_like = mid_s.startswith(
                ("meta/", "mistralai/", "openai/", "nvidia/", "google/", "microsoft/")
            )
            use_alt_provider = not nim_like
        if use_alt_provider:
            try:
                from src.core.llm_providers import resolve_provider_for_model

                provider = resolve_provider_for_model(model_id)
                t_attempt = time.perf_counter()
                text, meta = provider.chat(
                    model_id,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=float(getattr(timeout, "read", None) or hard_read),
                )
                if not text:
                    raise ValueError(f"Empty response from {model_id}")
                attempt_ms = (time.perf_counter() - t_attempt) * 1000.0
                attempts_log.append(
                    {
                        "model_id": model_id,
                        "attempt": 1,
                        "ok": True,
                        "duration_ms": round(attempt_ms, 1),
                        "http_status": 200,
                        "error": None,
                        "provider": meta.get("provider"),
                    }
                )
                if call_meta is not None:
                    call_meta.update(
                        {
                            "model_id": meta.get("model_id") or model_id,
                            "provider": meta.get("provider"),
                            "retry_count": retry_count,
                            "attempt_count": len(attempts_log),
                            "http_status": 200,
                            "call_ms": round((time.perf_counter() - t_call0) * 1000.0, 1),
                            "attempts": attempts_log,
                            "success": True,
                        }
                    )
                if return_timing:
                    return text, meta.get("model_id") or model_id, {
                        "ttft_ms": attempt_ms,
                        "ttlt_ms": attempt_ms,
                        "mode": "provider",
                        "model_used": meta.get("model_id") or model_id,
                    }
                return text, meta.get("model_id") or model_id
            except Exception as e:
                last_error = e if isinstance(e, Exception) else RuntimeError(str(e))
                log.warning("Provider %s failed for %s: %s", "ollama", model_id, e)
                continue

        if deadline_mono is not None:
            remaining = float(deadline_mono) - time.monotonic()
            if remaining <= max(1.0, connect_cap):
                last_error = NimApiError(
                    f"Shared call deadline exhausted before trying {model_id} "
                    f"(remaining={remaining:.1f}s)"
                )
                log.warning("%s", last_error)
                break
        model_attempts = max_retries_per_model * endpoint_retries
        for attempt in range(model_attempts):
            # Soft TTFT is enforced inside the stream helper (idle-to-first-token),
            # NOT by capping the whole HTTP read timeout — that was killing slow
            # medium/heavy models at 45s even while tokens were about to arrive.
            read_cap = float(getattr(base_timeout, "read", None) or hard_read)
            if deadline_mono is not None:
                remaining = float(deadline_mono) - time.monotonic()
                if remaining <= max(1.0, connect_cap):
                    last_error = NimApiError(
                        f"Shared call deadline exhausted during {model_id} "
                        f"(remaining={remaining:.1f}s)"
                    )
                    log.warning("%s", last_error)
                    break
                req_timeout = httpx.Timeout(
                    max(1.0, min(read_cap, remaining - 0.5)),
                    connect=min(connect_cap, max(1.0, remaining - 0.5)),
                )
            else:
                req_timeout = httpx.Timeout(read_cap, connect=connect_cap)
            t_attempt = time.perf_counter()
            try:
                _raise_if_deadline(f"before_http:{model_id}")
                # Global throttle — workers queue on the limiter, not each other.
                from src.core.nim_rate_limit import acquire_nim_request_slot

                acquire_timeout = None
                if deadline_mono is not None:
                    acquire_timeout = max(0.5, float(deadline_mono) - time.monotonic() - 0.5)
                acquire_nim_request_slot(timeout_sec=acquire_timeout)
                log.info(
                    "TASK_LIFECYCLE phase=HTTP_REQUEST_STARTED task=%s model=%s "
                    "endpoint=%s read_timeout=%.1fs deadline_left=%.1fs",
                    task_id,
                    model_id,
                    lease.endpoint_id if lease else "primary",
                    float(getattr(req_timeout, "read", None) or 0.0),
                    _deadline_left(),
                )
                if measure_ttft:
                    text, timing = _chat_completion_with_ttft(
                        client,
                        model_id=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=req_timeout,
                        soft_ttft_timeout_sec=soft_ttft if use_soft_ttft else None,
                        deadline_mono=deadline_mono,
                        task_id=task_id,
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
                log.info(
                    "TASK_LIFECYCLE phase=RESPONSE_RECEIVED task=%s model=%s "
                    "chars=%s endpoint=%s",
                    task_id,
                    model_id,
                    len(text or ""),
                    lease.endpoint_id if lease else "primary",
                )
                if not text:
                    raise ValueError(f"Empty response from {model_id}")
                attempt_ms = (time.perf_counter() - t_attempt) * 1000.0
                ttft_ms = float((timing or {}).get("ttft_ms") or 0.0)
                log.info(
                    "TASK_LIFECYCLE phase=SUMMARY_PARSED task=%s model=%s "
                    "chars=%s ttft_ms=%.1f call_ms=%.1f",
                    task_id,
                    model_id,
                    len(text),
                    ttft_ms,
                    attempt_ms,
                )
                attempts_log.append(
                    {
                        "model_id": model_id,
                        "attempt": attempt + 1,
                        "ok": True,
                        "duration_ms": round(attempt_ms, 1),
                        "http_status": 200,
                        "error": None,
                        "endpoint_id": lease.endpoint_id if lease else None,
                    }
                )
                log.info(
                    "Chat succeeded with model '%s' endpoint=%s",
                    model_id,
                    lease.endpoint_id if lease else "primary",
                )
                if call_meta is not None:
                    call_meta.update(
                        {
                            "model_id": model_id,
                            "retry_count": retry_count,
                            "attempt_count": len(attempts_log),
                            "http_status": 200,
                            "call_ms": round((time.perf_counter() - t_call0) * 1000.0, 1),
                            "attempts": attempts_log,
                            "success": True,
                            "fallback_used": model_id != ordered_ids[0] if ordered_ids else False,
                            "primary_model": ordered_ids[0] if ordered_ids else None,
                            "endpoint_id": lease.endpoint_id if lease else None,
                        }
                    )
                if use_pool and pool_mod is not None and lease is not None:
                    pool_mod.release_endpoint(
                        lease,
                        ok=True,
                        latency_ms=attempt_ms,
                        ttft_ms=ttft_ms,
                        rate_limited=False,
                    )
                    lease = None
                if return_timing:
                    timing_out = dict(timing or {})
                    timing_out.update(
                        {
                            "retry_count": retry_count,
                            "attempt_count": len(attempts_log),
                            "attempts": attempts_log,
                            "fallback_used": model_id != ordered_ids[0] if ordered_ids else False,
                            "primary_model": ordered_ids[0] if ordered_ids else None,
                            "model_used": model_id,
                            "http_status": 200,
                        }
                    )
                    return text, model_id, timing_out
                return text, model_id
            except Exception as e:
                from src.core.nim_rate_limit import RateLimitBackpressure

                # Propagate rate-limit backpressure immediately (no classify delay).
                if isinstance(e, RateLimitBackpressure):
                    raise
                classified = _classify_nim_exception(e, model_id=model_id)
                if isinstance(classified, RateLimitBackpressure):
                    from src.core.nim_rate_limit import record_rate_limit_signal

                    record_rate_limit_signal()
                    if use_pool and pool_mod is not None and lease is not None:
                        try:
                            pool_mod.release_endpoint(
                                lease,
                                ok=False,
                                latency_ms=(time.perf_counter() - t_attempt) * 1000.0,
                                rate_limited=True,
                                timed_out=False,
                            )
                        except Exception:
                            pass
                        lease = None
                    raise classified
                last_error = classified if isinstance(classified, Exception) else e
                err_str = str(e)
                http_status = _http_status_from_exc(classified)
                if http_status is None:
                    http_status = _http_status_from_exc(e)
                last_http_status = http_status
                attempt_ms = (time.perf_counter() - t_attempt) * 1000.0
                is_soft = "soft_ttft" in err_str.lower() or "soft ttft" in err_str.lower()
                is_timeout = (
                    is_soft
                    or isinstance(classified, (APITimeoutError, TimeoutError))
                    or "timeout" in err_str.lower()
                )
                attempts_log.append(
                    {
                        "model_id": model_id,
                        "attempt": attempt + 1,
                        "ok": False,
                        "duration_ms": round(attempt_ms, 1),
                        "http_status": http_status,
                        "error": f"{type(classified).__name__}: {str(classified)[:180]}",
                        "endpoint_id": lease.endpoint_id if lease else None,
                        "soft_ttft": is_soft,
                    }
                )
                is_rate_limit = (
                    http_status == 429
                    or "429" in err_str
                    or "rate limit" in err_str.lower()
                    or (
                        _OpenAIRateLimitError
                        and isinstance(e, _OpenAIRateLimitError)
                    )
                )
                # Rate-limit is backpressure for the pool — do not burn the
                # hard-isolation wall with intra-call sleeps/retries.
                if is_rate_limit:
                    from src.core.nim_rate_limit import record_rate_limit_signal

                    record_rate_limit_signal()
                    if use_pool and pool_mod is not None and lease is not None:
                        pool_mod.release_endpoint(
                            lease,
                            ok=False,
                            latency_ms=attempt_ms,
                            rate_limited=True,
                            timed_out=False,
                        )
                        lease = None
                    raise RateLimitBackpressure(
                        f"NIM rate limit on {model_id}",
                        retry_after_sec=getattr(classified, "retry_after_sec", None),
                        status_code=429,
                    )

                # Retry only on timeout / 5xx / connection (and soft TTFT).
                retryable = (
                    is_soft
                    or is_timeout
                    or is_transient_nim_error(classified)
                    or (http_status is not None and http_status >= 500)
                )

                failed_ep = lease.endpoint_id if lease else None
                if use_pool and pool_mod is not None and lease is not None:
                    pool_mod.release_endpoint(
                        lease,
                        ok=False,
                        latency_ms=attempt_ms,
                        rate_limited=False,
                        timed_out=is_timeout,
                    )
                    lease = None
                if failed_ep:
                    exclude_endpoints.add(failed_ep)

                if retryable and attempt < model_attempts - 1:
                    retry_count += 1
                    # Prefer another endpoint on the SAME model before falling through.
                    client = _acquire_client()
                    if client is None:
                        break
                    wait = 0.5 if is_soft else 0.25
                    if deadline_mono is not None:
                        wait = min(
                            wait, max(0.0, float(deadline_mono) - time.monotonic() - 1.0)
                        )
                    log.warning(
                        "NIM retry model=%s endpoint_rotate=%s reason=%s attempt=%s/%s",
                        model_id,
                        failed_ep,
                        type(classified).__name__,
                        attempt + 1,
                        model_attempts,
                    )
                    if wait > 0:
                        time.sleep(wait)
                    continue

                log.warning(
                    "Model '%s' failed on all tried endpoints (%s): %s. "
                    "Trying next fallback if any.",
                    model_id,
                    type(classified).__name__,
                    classified,
                )
                exclude_endpoints.clear()
                client = _acquire_client()
                break  # next model
        else:
            continue
        if deadline_mono is not None and (float(deadline_mono) - time.monotonic()) <= max(
            1.0, connect_cap
        ):
            break

    if use_pool and pool_mod is not None and lease is not None:
        pool_mod.release_endpoint(lease, ok=False, latency_ms=0.0, rate_limited=False)
        lease = None

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
    soft_ttft_timeout_sec: Optional[float] = None,
    deadline_mono: Optional[float] = None,
    task_id: str = "-",
) -> Tuple[str, Dict[str, Any]]:
    """
    Stream the completion solely to separate TTFT from TTLT.
    Accumulates the full text; does not change the upstream response shape.
    Falls back to a blocking call if streaming is unsupported.

    When ``soft_ttft_timeout_sec`` is set and no content token arrives in time,
    raises ``NimApiError`` with ``soft_ttft`` so the caller can rotate endpoints.
    """
    t0 = time.perf_counter()
    ttft_ms: Optional[float] = None
    first_byte_ms: Optional[float] = None
    parts: List[str] = []
    soft = float(soft_ttft_timeout_sec) if soft_ttft_timeout_sec else 0.0
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
            if deadline_mono is not None and time.monotonic() >= float(deadline_mono):
                raise NimApiError(
                    f"Shared call deadline exhausted during stream on {model_id}"
                )
            if first_byte_ms is None:
                first_byte_ms = (time.perf_counter() - t0) * 1000.0
            if soft > 0 and ttft_ms is None and (time.perf_counter() - t0) >= soft:
                raise NimApiError(
                    f"soft_ttft timeout after {soft:.0f}s on {model_id} "
                    f"(no first token)"
                )
            try:
                delta = chunk.choices[0].delta.content if chunk.choices else None
            except (IndexError, AttributeError):
                delta = None
            if delta:
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                    log.info(
                        "TASK_LIFECYCLE phase=TTFT_RECEIVED task=%s model=%s "
                        "ttft_ms=%.1f",
                        task_id,
                        model_id,
                        ttft_ms,
                    )
                    log.info(
                        "TASK_LIFECYCLE phase=TOKEN_STREAM_STARTED task=%s model=%s",
                        task_id,
                        model_id,
                    )
                parts.append(delta)
        text = "".join(parts).strip()
        ttlt_ms = (time.perf_counter() - t0) * 1000.0
        if first_byte_ms is None:
            first_byte_ms = ttlt_ms
        if ttft_ms is None:
            if soft > 0:
                raise NimApiError(
                    f"soft_ttft timeout after {soft:.0f}s on {model_id} "
                    f"(stream ended without content)"
                )
            ttft_ms = ttlt_ms
        return text, {
            "request_start_ms": 0.0,
            "first_byte_ms": round(first_byte_ms, 3),
            "ttft_ms": round(ttft_ms, 3),
            "ttlt_ms": round(ttlt_ms, 3),
            "network_ms": round(first_byte_ms, 3),
            "inference_ms": round(max(0.0, ttlt_ms - first_byte_ms), 3),
            "mode": "stream_measure",
            "http_status": 200,
        }
    except NimApiError:
        raise
    except Exception as e:
        # Soft timeout must not fall through to a long blocking call.
        if soft > 0 and (time.perf_counter() - t0) >= soft * 0.9:
            raise NimApiError(
                f"soft_ttft timeout after {soft:.0f}s on {model_id}",
                cause=e,
            ) from e
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
            "request_start_ms": 0.0,
            "first_byte_ms": round(elapsed, 3),
            "ttft_ms": round(elapsed, 3),
            "ttlt_ms": round(elapsed, 3),
            "network_ms": round(elapsed, 3),
            "inference_ms": 0.0,
            "mode": "blocking_ttft_equals_ttlt",
            "stream_error": str(e)[:200],
            "http_status": 200,
        }


def iter_chat_stream_with_fallback(
    model_ids: List[str],
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.5,
    max_tokens: int = 2000,
    max_retries_per_model: Optional[int] = None,
    timeout: Optional[httpx.Timeout] = None,
    call_meta: Optional[Dict[str, Any]] = None,
):
    """
    Yield ``("token", delta)`` then ``("done", {model_id, timing})``.
    Falls through models on transient errors (same policy as call_chat_with_fallback).
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

    seen: set = set()
    ordered_ids: List[str] = []
    for mid in model_ids or []:
        if mid and mid not in seen:
            seen.add(mid)
            ordered_ids.append(mid)

    for model_id in ordered_ids:
        for attempt in range(max_retries_per_model):
            t_attempt = time.perf_counter()
            ttft_ms: Optional[float] = None
            first_byte_ms: Optional[float] = None
            parts: List[str] = []
            try:
                t0 = time.perf_counter()
                stream = client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=req_timeout,
                    stream=True,
                )
                for chunk in stream:
                    if first_byte_ms is None:
                        first_byte_ms = (time.perf_counter() - t0) * 1000.0
                    try:
                        delta = chunk.choices[0].delta.content if chunk.choices else None
                    except (IndexError, AttributeError):
                        delta = None
                    if delta:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t0) * 1000.0
                        parts.append(delta)
                        yield ("token", delta)
                text = "".join(parts).strip()
                if not text:
                    raise ValueError(f"Empty response from {model_id}")
                ttlt_ms = (time.perf_counter() - t0) * 1000.0
                if first_byte_ms is None:
                    first_byte_ms = ttlt_ms
                if ttft_ms is None:
                    ttft_ms = ttlt_ms
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
                timing = {
                    "request_start_ms": 0.0,
                    "first_byte_ms": round(first_byte_ms, 3),
                    "ttft_ms": round(ttft_ms, 3),
                    "ttlt_ms": round(ttlt_ms, 3),
                    "network_ms": round(first_byte_ms, 3),
                    "inference_ms": round(max(0.0, ttlt_ms - first_byte_ms), 3),
                    "mode": "client_stream",
                    "http_status": 200,
                    "retry_count": retry_count,
                    "attempt_count": len(attempts_log),
                    "attempts": attempts_log,
                    "fallback_used": model_id != ordered_ids[0] if ordered_ids else False,
                    "primary_model": ordered_ids[0] if ordered_ids else None,
                    "model_used": model_id,
                }
                if call_meta is not None:
                    call_meta.update(
                        {
                            "model_id": model_id,
                            "retry_count": retry_count,
                            "attempt_count": len(attempts_log),
                            "http_status": 200,
                            "call_ms": round((time.perf_counter() - t_call0) * 1000.0, 1),
                            "attempts": attempts_log,
                            "success": True,
                            "fallback_used": timing["fallback_used"],
                            "primary_model": timing["primary_model"],
                        }
                    )
                yield ("done", {"model_id": model_id, "timing": timing})
                return
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
                # If we already streamed tokens, do not silently switch models
                if parts:
                    raise
                if transient and attempt < max_retries_per_model - 1:
                    retry_count += 1
                    wait = (3 * (attempt + 1)) if is_rate_limit else (2 ** attempt)
                    log.warning(
                        "Transient NIM stream error on %s (%s). Retrying in %ss...",
                        model_id,
                        type(classified).__name__,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                log.warning(
                    "Stream model '%s' failed (%s). Trying next fallback if any.",
                    model_id,
                    type(classified).__name__,
                )
                break

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
    deadline_mono: Optional[float] = None,
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
            deadline_mono=deadline_mono,
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
    max_models: int = 3,
) -> List[List[str]]:
    """
    Ordered unique model chain(s) for compile.

    Collapses medium/heavy/light into one de-duplicated list (heavy primary is
    often the same id as medium). Caps length so a stalled NIM call cannot
    burn 10+ minutes walking a redundant ladder.
    """
    use_medium_first = (
        bool(settings.COMPILE_MEDIUM_FIRST)
        if medium_first is None
        else bool(medium_first)
    )
    if use_medium_first:
        sources = (
            list(primary or []) or list(settings.medium_models()),
            list(settings.medium_models()),
            list(settings.heavy_models()),
            list(settings.light_models()),
        )
    else:
        sources = (
            list(primary or []) or list(settings.heavy_models()),
            list(settings.medium_models()),
            list(settings.light_models()),
        )
    unique: List[str] = []
    seen: set = set()
    for chain in sources:
        for mid in chain:
            if mid and mid not in seen:
                seen.add(mid)
                unique.append(mid)
            if len(unique) >= max(1, int(max_models or 3)):
                return [unique]
    return [unique] if unique else []


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


def _compile_timeout(*, remaining_sec: Optional[float] = None) -> httpx.Timeout:
    """HTTP timeout for compile calls — always strictly below COMPILE_CALL_MAX_SEC."""
    read = float(getattr(settings, "NIM_COMPILE_TIMEOUT_SEC", 55.0) or 55.0)
    wall = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
    # Keep HTTP abort below the wrapper wall so the worker thread can return.
    read = min(read, max(1.0, wall - 1.0))
    if remaining_sec is not None:
        read = max(1.0, min(read, float(remaining_sec) - 0.5))
    return _nim_timeout(read_override=read)


def _shutdown_executor_nowait(pool: Any, fut: Any = None) -> None:
    """Release the job without joining a hung NIM thread."""
    try:
        if fut is not None:
            fut.cancel()
    except Exception:
        pass
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        # Python < 3.9: cancel_futures unavailable
        try:
            pool.shutdown(wait=False)
        except Exception:
            pass
    except Exception:
        pass


def stitch_compile_fallback(
    summaries: Union[str, List[str]],
    *,
    reason: str = "NIM compile unavailable",
) -> str:
    """Last-resort executive summary from chunk/regional texts (no LLM)."""
    usable = _normalize_compile_summaries(summaries)
    stitched = "\n\n".join(f"- {s}" for s in usable[:40])
    if not stitched.strip():
        return (
            "Unable to generate a final summary because no usable chunk summaries "
            "were produced. Please retry the upload."
        )
    return (
        "## Summary\n\n"
        f"The executive compile step could not complete ({reason}), "
        "so this is a stitched fallback from chunk summaries:\n\n"
        f"{stitched}"
    )


def is_stitched_fallback(text: Optional[str]) -> bool:
    """True when text is the deterministic stitched compile fallback (not LLM)."""
    low = str(text or "").strip().lower()
    if not low:
        return False
    return "stitched fallback from chunk summaries" in low


def is_executive_compile_success(text: Optional[str]) -> bool:
    """
    True when text is a durable executive compile artifact (usable LLM output).
    Stitched fallbacks and empty/error markers are not successes.
    """
    if is_stitched_fallback(text):
        return False
    return _is_usable_summary(str(text or ""))


def _call_compile_llm(
    text_of_summaries: str,
    chain: List[str],
    *,
    intermediate: bool = False,
    deadline_mono: Optional[float] = None,
) -> Tuple[str, Optional[str]]:
    messages = [
        {"role": "system", "content": _COMPILE_SYSTEM},
        {
            "role": "user",
            "content": _build_compile_prompt(text_of_summaries, intermediate=intermediate),
        },
    ]
    wall = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
    started = time.monotonic()
    if deadline_mono is None:
        deadline_mono = started + wall
    # Shared budget for the whole fallback chain (not per-model stacking).
    hard_sec = max(0.5, min(wall, float(deadline_mono) - started))

    # Hedged compile: fire fallback concurrently if primary exceeds its slice.
    # Carbon/cost tradeoff: when hedge fires, up to ~2 concurrent compile NIM
    # calls may run briefly; gated by COMPILE_HEDGED_FALLBACK_ENABLED.
    hedged = bool(getattr(settings, "COMPILE_HEDGED_FALLBACK_ENABLED", False))
    if hedged and len([m for m in (chain or []) if m]) >= 2:
        return _call_compile_llm_hedged(
            messages,
            chain,
            intermediate=intermediate,
            deadline_mono=deadline_mono,
            hard_sec=hard_sec,
        )

    def _invoke() -> Tuple[str, Optional[str]]:
        remaining = float(deadline_mono) - time.monotonic()
        # No per-model retries — long compile prompts must fall through quickly.
        return call_chat_with_fallback(
            chain,
            messages,
            temperature=0.5,
            max_tokens=1600 if intermediate else 2000,
            max_retries_per_model=1,
            timeout=_compile_timeout(remaining_sec=remaining),
            deadline_mono=deadline_mono,
            call_meta={"phase": "compile", "endpoint_role": "compile"},
        )

    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_invoke)
    try:
        return fut.result(timeout=hard_sec)
    except concurrent.futures.TimeoutError as e:
        raise NimApiError(
            f"Compile hard timeout after {hard_sec:.0f}s "
            f"(models={chain})"
        ) from e
    finally:
        # Critical: do not join a hung socket thread — let HTTP timeout reclaim it.
        _shutdown_executor_nowait(pool, fut)


def _call_compile_llm_hedged(
    messages: List[Dict[str, str]],
    chain: List[str],
    *,
    intermediate: bool,
    deadline_mono: float,
    hard_sec: float,
) -> Tuple[str, Optional[str]]:
    """
    Hedged compile fallback.

    Primary runs alone for its allocated slice. If it has not returned, the next
    fallback is started concurrently; first successful response wins and the
    loser is abandoned via non-blocking executor shutdown.

    Carbon/cost: hedge may briefly double compile NIM spend when primary is slow.
    """
    from src.core.chain_time_budget import (
        get_reliability_tracker,
        log_slice_report,
        plan_chain_slices,
    )
    import concurrent.futures

    seen: set = set()
    ordered: List[str] = []
    for mid in chain or []:
        if mid and mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    if not ordered:
        raise RuntimeError("Empty compile chain")

    wall_sec = max(0.5, min(hard_sec, float(deadline_mono) - time.monotonic()))
    ordered, slices, report = plan_chain_slices(
        ordered, role="compile", wall_sec=wall_sec
    )
    tracker = get_reliability_tracker()
    primary = ordered[0]
    primary_slice = float(slices[0])
    max_tokens = 1600 if intermediate else 2000

    def _one(model_id: str, model_deadline: float, call_meta: Dict[str, Any]):
        remaining = max(0.5, float(model_deadline) - time.monotonic())
        return call_chat_with_fallback(
            [model_id],
            messages,
            temperature=0.5,
            max_tokens=max_tokens,
            max_retries_per_model=1,
            timeout=_compile_timeout(remaining_sec=remaining),
            deadline_mono=model_deadline,
            call_meta=call_meta,
        )

    primary_meta: Dict[str, Any] = {
        "phase": "compile",
        "endpoint_role": "compile",
        "hedged": True,
        "chain_position": 0,
    }
    primary_deadline = min(float(deadline_mono), time.monotonic() + primary_slice)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    primary_fut = pool.submit(_one, primary, primary_deadline, primary_meta)
    t0 = time.monotonic()
    winner: Optional[Tuple[str, Optional[str]]] = None
    winner_model = None
    primary_failed_early = False

    try:
        try:
            winner = primary_fut.result(timeout=max(0.5, primary_slice))
            winner_model = primary
            used = time.monotonic() - t0
            report.attempts[0].used_sec = used
            report.attempts[0].outcome = "success"
            tracker.record(primary, ok=True)
            log.info(
                "CHAIN_SLICE hedged_compile primary=%s alloc=%.1fs used=%.1fs "
                "outcome=success (no hedge needed)",
                primary,
                primary_slice,
                used,
            )
        except concurrent.futures.TimeoutError:
            used = time.monotonic() - t0
            report.attempts[0].used_sec = used
            report.attempts[0].outcome = "timeout_slice"
            report.attempts[0].error = "primary_slice_elapsed_hedging"
            tracker.record(primary, ok=False, timeout=True)
            log.warning(
                "CHAIN_SLICE hedged_compile primary=%s alloc=%.1fs used=%.1fs "
                "— launching concurrent fallback (extra NIM spend)",
                primary,
                primary_slice,
                used,
            )
        except Exception as e:
            used = time.monotonic() - t0
            report.attempts[0].used_sec = used
            report.attempts[0].outcome = "error"
            report.attempts[0].error = f"{type(e).__name__}: {str(e)[:120]}"
            tracker.record(primary, ok=False, error=True)
            primary_failed_early = True
            log.warning(
                "CHAIN_SLICE hedged_compile primary=%s failed early: %s — hedging",
                primary,
                e,
            )

        if winner is None:
            # Fire remaining fallbacks concurrently; take first success.
            # Include still-running primary on timeout path (it may still win).
            futs: Dict[concurrent.futures.Future, Tuple[int, str]] = {}
            if not primary_failed_early and not primary_fut.done():
                futs[primary_fut] = (0, primary)
            for i, mid in enumerate(ordered[1:], start=1):
                slice_i = float(slices[i] if i < len(slices) else slices[-1])
                md = min(float(deadline_mono), time.monotonic() + slice_i)
                if md - time.monotonic() < 0.75:
                    report.attempts[i].outcome = "skipped"
                    continue
                meta = {
                    "phase": "compile",
                    "endpoint_role": "compile",
                    "hedged": True,
                    "chain_position": i,
                }
                f = pool.submit(_one, mid, md, meta)
                futs[f] = (i, mid)

            if not futs:
                log_slice_report(report)
                raise NimApiError(
                    f"Hedged compile: no runnable fallbacks within {hard_sec:.0f}s"
                )

            remaining_wall = max(0.5, float(deadline_mono) - time.monotonic())
            done, _pending = concurrent.futures.wait(
                list(futs.keys()),
                timeout=remaining_wall,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                idx, mid = futs[fut]
                try:
                    winner = fut.result(timeout=0)
                    winner_model = mid
                    used_i = time.monotonic() - t0
                    report.attempts[idx].used_sec = used_i
                    report.attempts[idx].outcome = "success"
                    tracker.record(mid, ok=True)
                    for other, (oj, om) in futs.items():
                        if other is fut:
                            continue
                        if report.attempts[oj].outcome in ("pending", "timeout_slice"):
                            report.attempts[oj].outcome = "cancelled"
                            report.attempts[oj].used_sec = used_i
                            report.attempts[oj].error = "cancelled_hedge_loser"
                    log.info(
                        "CHAIN_SLICE hedged_compile winner=%s pos=%s wall_used=%.1fs",
                        mid,
                        idx,
                        used_i,
                    )
                    break
                except Exception as e:
                    report.attempts[idx].outcome = "error"
                    report.attempts[idx].error = f"{type(e).__name__}: {str(e)[:120]}"
                    report.attempts[idx].used_sec = time.monotonic() - t0
                    tracker.record(mid, ok=False, error=True)
            if winner is None:
                for fut, (idx, mid) in futs.items():
                    if fut.done():
                        try:
                            winner = fut.result(timeout=0)
                            winner_model = mid
                            report.attempts[idx].outcome = "success"
                            tracker.record(mid, ok=True)
                            break
                        except Exception:
                            continue
                if winner is None:
                    log_slice_report(report)
                    raise NimApiError(
                        f"Hedged compile failed within {hard_sec:.0f}s "
                        f"(models={ordered})"
                    )
        log_slice_report(report)
        return winner
    finally:
        _shutdown_executor_nowait(pool, primary_fut)


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
    *,
    deadline_mono: Optional[float] = None,
) -> str:
    """
    Batch large summary sets into intermediate compiles, then final compile.
    Falls through model chains on each step.

    Intermediate batches within a round run concurrently (COMPILE_MAX_WORKERS)
    — same inputs/outputs as sequential; lower wall-clock only.

    ``deadline_mono`` is a shared wall for this entire compile invocation
    (batches + final + all model fallbacks).
    """
    import concurrent.futures

    batch_size = max(3, int(getattr(settings, "COMPILE_BATCH_SIZE", 8) or 8))
    max_tokens = int(getattr(settings, "COMPILE_MAX_INPUT_TOKENS", 10000) or 10000)
    compile_workers = max(1, int(getattr(settings, "COMPILE_MAX_WORKERS", 4) or 4))
    wall = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
    if deadline_mono is None:
        deadline_mono = time.monotonic() + wall

    working = list(summaries)
    round_idx = 0

    def _deadline_left() -> float:
        return float(deadline_mono) - time.monotonic()

    def _compile_one_batch(bi: int, batch: List[str], batch_total: int) -> tuple:
        batch_text = "\n\n".join(batch)
        last_err: Optional[Exception] = None
        job_id = state.get("job_id")
        # Intermediate batches: at most 2 unique models (skip full ladder).
        primary = list(chains[0]) if chains else []
        batch_chains = [primary[:2]] if primary else []
        if _deadline_left() <= 2.0:
            return bi, batch_text, None, len(batch_text), NimApiError(
                "Compile deadline exhausted before intermediate batch"
            )
        if job_id:
            try:
                from src.db import jobs as jobs_db

                model_hint = (batch_chains[0][0] if batch_chains and batch_chains[0] else "?")
                jobs_db.set_progress(
                    job_id,
                    min(90.0, 82.0 + (8.0 * bi / max(batch_total, 1))),
                    f"Compiling summary batches... ({bi}/{batch_total}) · {model_hint}",
                )
            except Exception:
                pass
        log.info(
            "Compile round %s batch %s/%s (~%s tokens) models=%s",
            round_idx,
            bi,
            batch_total,
            _estimate_compile_tokens(batch_text),
            [c[0] for c in batch_chains if c],
        )
        for chain in batch_chains:
            try:
                text, used = _call_compile_llm(
                    batch_text,
                    chain,
                    intermediate=True,
                    deadline_mono=deadline_mono,
                )
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
        if _deadline_left() <= 2.0:
            raise NimApiError("Compile deadline exhausted during hierarchical batching")
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
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
            try:
                futs = [
                    pool.submit(_compile_one_batch, bi, batch, batch_total)
                    for bi, batch in batches
                ]
                for fut in concurrent.futures.as_completed(futs):
                    bi2, text, used, nchars, err = fut.result()
                    results_by_bi[bi2] = (text, used, nchars)
            finally:
                _shutdown_executor_nowait(pool)

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
    job_id = state.get("job_id")
    for chain in chains:
        if _deadline_left() <= 2.0:
            last_error = NimApiError("Compile deadline exhausted before final chain")
            break
        if job_id and chain:
            try:
                from src.db import jobs as jobs_db
                from src.perf.critical_path import dag_audit_record_compile_stamp

                kind = str(state.get("_compile_audit_kind") or "executive")
                nid = state.get("_compile_audit_nid")
                # Truthful progress — never say "Executive" while compiling regional/chapter.
                kind_label = {
                    "regional": "Regional Summaries",
                    "chapter": "Chapter Summaries",
                    "executive": "Executive Summary",
                    "final": "Executive Summary",
                    "compile": "Compile",
                    "chunk": "Chunk Summaries",
                }.get(kind, "Summary")
                msg = f"{kind_label}… · {chain[0]}"
                dag_audit_record_compile_stamp(
                    str(job_id),
                    kind=kind,
                    nid=str(nid) if nid else None,
                    message=msg,
                )
                jobs_db.set_progress(
                    job_id,
                    88.0,
                    msg,
                )
            except Exception:
                pass
        try:
            result, used = _call_compile_llm(
                final_text,
                chain,
                intermediate=False,
                deadline_mono=deadline_mono,
            )
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
    *,
    deadline_mono: Optional[float] = None,
) -> str:
    """
    Compile chunk summaries using the router-selected chain, with:
    - hierarchical batching for large documents
    - cross-tier fallback under a single COMPILE_CALL_MAX_SEC budget
    - HTTP + wrapper timeouts that actually release the job
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
    wall = float(getattr(settings, "COMPILE_CALL_MAX_SEC", 180.0) or 180.0)
    if deadline_mono is None:
        deadline_mono = time.monotonic() + wall
    log.info(
        "Compile starting: summaries=%s tokens≈%s primary_models=%s budget_sec=%.0f",
        len(summaries),
        _estimate_compile_tokens("\n\n".join(summaries)),
        [c[0] for c in chains if c],
        max(0.0, float(deadline_mono) - time.monotonic()),
    )

    try:
        return strip_outer_markdown_fence(
            _hierarchical_compile(
                summaries, chains, state, deadline_mono=deadline_mono
            )
        )
    except Exception as e:
        log.error(f"Error in compile: {e}")
        # Last-resort: stitch usable chunk summaries so the job still has content
        out = stitch_compile_fallback(summaries, reason=str(e)[:160])
        if out.startswith("Unable to generate"):
            return f"Final summary generation failed: {e}"
        log.warning("Returning stitched chunk-summary fallback after compile failure")
        return out


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

    Side effect: updates ``models_registry["last_embed_meta"]`` with measured
    latency / cache hit-miss for the latest call (instrumentation only).
    """
    client = get_nim_client()
    if client is None:
        raise RuntimeError("NVIDIA NIM client is not configured (missing NVIDIA_API_KEY).")

    if not texts:
        models_registry["last_embed_meta"] = {
            "embedding_model": settings.EMBEDDING_MODEL,
            "input_type": input_type,
            "texts": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "embed_api_ms": 0.0,
        }
        return []

    model_id = settings.EMBEDDING_MODEL
    use_cache = bool(getattr(settings, "ENABLE_EMBEDDING_CACHE", True))
    itype = (input_type or "passage").strip() or "passage"
    t0 = time.perf_counter()

    if use_cache:
        from src.memory import embedding_cache

        cached, miss_indices = embedding_cache.get_many(model_id, texts, input_type=itype)
        hits = len(texts) - len(miss_indices)
        misses = len(miss_indices)
        if not miss_indices:
            models_registry["last_embed_meta"] = {
                "embedding_model": model_id,
                "input_type": itype,
                "texts": len(texts),
                "cache_hits": hits,
                "cache_misses": 0,
                "embed_api_ms": 0.0,
                "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                "dim": len(cached[0]) if cached and cached[0] else None,
            }
            return [v for v in cached]  # type: ignore[misc]

        to_embed = [texts[i] for i in miss_indices]
        t_api = time.perf_counter()
        fresh = _embed_batch_nim(client, model_id, to_embed, input_type=itype)
        api_ms = (time.perf_counter() - t_api) * 1000.0
        embedding_cache.put_many(model_id, to_embed, fresh, input_type=itype)
        out: List[List[float]] = []
        fresh_iter = iter(fresh)
        for i, existing in enumerate(cached):
            if existing is not None:
                out.append(existing)
            else:
                out.append(next(fresh_iter))
        models_registry["last_embed_meta"] = {
            "embedding_model": model_id,
            "input_type": itype,
            "texts": len(texts),
            "cache_hits": hits,
            "cache_misses": misses,
            "embed_api_ms": round(api_ms, 3),
            "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "dim": len(out[0]) if out else None,
        }
        return out

    t_api = time.perf_counter()
    vectors = _embed_batch_nim(client, model_id, texts, input_type=itype)
    api_ms = (time.perf_counter() - t_api) * 1000.0
    models_registry["last_embed_meta"] = {
        "embedding_model": model_id,
        "input_type": itype,
        "texts": len(texts),
        "cache_hits": 0,
        "cache_misses": len(texts),
        "embed_api_ms": round(api_ms, 3),
        "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        "dim": len(vectors[0]) if vectors else None,
    }
    return vectors


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
# Reranking (NVIDIA retrieval API)
# ---------------------------------------------------------------------------

# Process-level circuit: after a hard 404, skip further network calls this process.
_rerank_disabled_reason: Optional[str] = None


def _rerank_urls() -> List[str]:
    """
    Candidate endpoints. integrate.api .../v1/ranking returns 404 on the cloud
    trial; the documented retrieval path is:
      https://ai.api.nvidia.com/v1/retrieval/nvidia/<model>/reranking
    """
    model = (settings.RERANK_MODEL or "").strip()
    short = model.split("/")[-1] if model else "llama-nemotron-rerank-1b-v2"
    urls: List[str] = []
    # Preferred cloud retrieval API
    urls.append(
        f"https://ai.api.nvidia.com/v1/retrieval/nvidia/{short}/reranking"
    )
    # Legacy / local NIM path
    base = settings.NVIDIA_BASE_URL.rstrip("/")
    urls.append(f"{base}/ranking")
    # Dedupe
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def rerank(query: str, passages: List[str], top_k: int) -> List[str]:
    """
    Rerank passages against a query using NVIDIA NIM ranking API.
    Returns the top_k passages in relevance order.
    On failure / circuit-open, returns the original passages truncated to top_k
    without waiting on a guaranteed-404 endpoint.
    """
    global _rerank_disabled_reason

    if not passages:
        models_registry["last_rerank_meta"] = {
            "status": "empty",
            "latency_ms": 0.0,
        }
        return []

    top_k = max(1, min(top_k, len(passages)))
    t0 = time.perf_counter()

    if not bool(getattr(settings, "ENABLE_RERANK", True)):
        models_registry["last_rerank_meta"] = {
            "status": "disabled_config",
            "latency_ms": 0.0,
        }
        return passages[:top_k]

    if _rerank_disabled_reason:
        models_registry["last_rerank_meta"] = {
            "status": "circuit_open",
            "reason": _rerank_disabled_reason,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }
        return passages[:top_k]

    if get_nim_client() is None or not settings.NVIDIA_API_KEY:
        log.warning("Reranker unavailable; returning first top_k passages.")
        models_registry["last_rerank_meta"] = {
            "status": "no_client",
            "latency_ms": 0.0,
        }
        return passages[:top_k]

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
    # Fail fast — do not burn up to 60s on a broken endpoint
    rerank_timeout = float(getattr(settings, "RERANK_HTTP_TIMEOUT_SEC", 8.0) or 8.0)

    last_err: Optional[str] = None
    for url in _rerank_urls():
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=rerank_timeout
            )
            if resp.status_code == 404:
                last_err = f"404 {url}"
                log.warning("Rerank endpoint 404: %s — trying next", url)
                continue
            resp.raise_for_status()
            data = resp.json()
            rankings = data.get("rankings") or data.get("results") or []
            if not rankings:
                log.warning("Rerank returned empty rankings; using original order.")
                models_registry["last_rerank_meta"] = {
                    "status": "empty_rankings",
                    "url": url,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                }
                return passages[:top_k]

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
            if len(result) < top_k:
                for p in passages:
                    if p not in result:
                        result.append(p)
                    if len(result) >= top_k:
                        break

            log.info(f"Reranked {len(passages)} passages → top {len(result)} via {url}")
            models_registry["last_rerank_meta"] = {
                "status": "ok",
                "url": url,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                "input_passages": len(passages),
                "returned": len(result),
            }
            return result
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log.warning("Rerank attempt failed (%s): %s", url, e)
            continue

    # All endpoints failed — open circuit so subsequent queries skip the network
    _rerank_disabled_reason = last_err or "all_endpoints_failed"
    log.error(
        "Rerank unavailable (%s). Circuit open for this process; "
        "using original passage order.",
        _rerank_disabled_reason,
    )
    models_registry["last_rerank_meta"] = {
        "status": "failed_circuit_open",
        "reason": _rerank_disabled_reason,
        "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }
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
