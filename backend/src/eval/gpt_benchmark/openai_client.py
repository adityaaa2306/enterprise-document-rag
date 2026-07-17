"""
Direct OpenAI Chat Completions client for benchmarking.

Uses OPENAI_API_KEY from the environment / backend/.env.
Never uses the production NIM client or ResponseAgent.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.eval.gpt_benchmark.pricing import estimate_api_cost_usd, energy_tier_for_model


@dataclass
class ModelRunResult:
    model: str
    ok: bool
    answer: str = ""
    error: Optional[str] = None
    model_requested: str = ""
    model_returned: Optional[str] = None
    finish_reason: Optional[str] = None
    latency_ms: float = 0.0
    ttft_ms: Optional[float] = None
    tokens_per_sec: Optional[float] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_api_cost_usd: float = 0.0
    estimated_energy_kwh: float = 0.0
    estimated_energy_wh: float = 0.0
    estimated_co2e_g: float = 0.0
    energy_tier: str = "medium"
    carbon: Dict[str, Any] = field(default_factory=dict)
    usage_raw: Dict[str, Any] = field(default_factory=dict)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    input_verification: Dict[str, Any] = field(default_factory=dict)
    participant_kind: str = "openai"
    routing: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        row = {
            "model": self.model,
            "model_requested": self.model_requested or self.model,
            "model_returned": self.model_returned,
            "ok": self.ok,
            "answer": self.answer,
            "error": self.error,
            "finish_reason": self.finish_reason,
            "latency_ms": round(self.latency_ms, 3) if not self.dry_run else None,
            "ttft_ms": None if self.ttft_ms is None else round(self.ttft_ms, 3),
            "tokens_per_sec": (
                None if self.tokens_per_sec is None else round(self.tokens_per_sec, 4)
            ),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_api_cost_usd": round(self.estimated_api_cost_usd, 8),
            "estimated_energy_kwh": self.estimated_energy_kwh,
            "estimated_energy_wh": self.estimated_energy_wh,
            "estimated_co2e_g": self.estimated_co2e_g,
            "energy_tier": self.energy_tier,
            "carbon": self.carbon,
            "usage_raw": self.usage_raw,
            "provider_metadata": self.provider_metadata,
            "input_verification": self.input_verification,
            "participant_kind": self.participant_kind,
            "routing": self.routing,
        }
        if self.dry_run:
            row["dry_run"] = True
            ub = (self.provider_metadata or {}).get("estimated_api_cost_usd_upper_bound")
            if ub is not None:
                row["estimated_api_cost_usd_upper_bound"] = ub
            if (self.provider_metadata or {}).get("note"):
                row["note"] = self.provider_metadata["note"]
        return row


def load_openai_api_key() -> str:
    """Load OPENAI_API_KEY from process env, then backend/.env."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key:
        return key

    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            name, _, val = line.partition("=")
            if name.strip() != "OPENAI_API_KEY":
                continue
            val = val.strip().strip('"').strip("'")
            if val:
                os.environ.setdefault("OPENAI_API_KEY", val)
                return val

    raise RuntimeError(
        "OPENAI_API_KEY is not set. Add it to backend/.env before running benchmarks."
    )


def get_openai_client():
    from openai import OpenAI

    return OpenAI(api_key=load_openai_api_key())


def _supports_custom_temperature(model: str) -> bool:
    """
    GPT-5 / reasoning families currently reject non-default temperature.
    Omit the parameter so the API uses its default (comparable across models).
    """
    mid = (model or "").strip().lower()
    if mid.startswith("gpt-5"):
        return False
    if mid.startswith(("o1", "o3", "o4")):
        return False
    return True


def _completion_kwargs(
    *,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout_sec: float,
    use_max_completion_tokens: bool,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "timeout": timeout_sec,
    }
    if use_max_completion_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    if _supports_custom_temperature(model):
        kwargs["temperature"] = temperature
    return kwargs


def _estimate_tokens_fallback(text: str) -> int:
    return max(0, len(text or "") // 4)


def _tokens_per_sec(completion_tokens: int, latency_ms: float) -> Optional[float]:
    if latency_ms <= 0 or completion_tokens <= 0:
        return None
    return float(completion_tokens) / (float(latency_ms) / 1000.0)


def _attach_energy(
    result: ModelRunResult,
    *,
    query: str,
    context_tokens: int,
    retrieval_hits: int,
    inference_model: Optional[str] = None,
) -> None:
    """Estimate energy/CO₂e via existing helpers (read-only import)."""
    from src.carbon.accounting import estimate_rag_query_carbon
    from src.chunking.service import estimate_tokens

    tier = energy_tier_for_model(inference_model or result.model)
    report = estimate_rag_query_carbon(
        query_tokens=int(estimate_tokens(query) or 0),
        retrieved_context_tokens=int(context_tokens or 0),
        prompt_tokens=int(result.prompt_tokens or 0),
        output_tokens=int(result.completion_tokens or 0),
        inference_tier=tier,
        retrieval_hits=max(0, int(retrieval_hits or 0)),
        include_query_embedding=True,
    )
    result.energy_tier = tier
    result.estimated_energy_kwh = float(report.get("estimated_energy_kwh") or 0.0)
    result.estimated_energy_wh = float(report.get("estimated_energy_wh") or 0.0)
    result.estimated_co2e_g = float(report.get("estimated_gco2e") or 0.0)
    result.carbon = {
        "estimated_gco2e": report.get("estimated_gco2e"),
        "estimated_energy_kwh": report.get("estimated_energy_kwh"),
        "estimated_energy_wh": report.get("estimated_energy_wh"),
        "grid_intensity_gco2_kwh": report.get("grid_intensity_gco2_kwh"),
        "grid_zone": report.get("grid_zone"),
        "grid_source": report.get("grid_source"),
        "inference_tier": report.get("inference_tier"),
        "stages_gco2e": report.get("stages_gco2e"),
        "methodology_note": (
            "Benchmark uses estimate_rag_query_carbon read-only; "
            "production Interactive RAG accounting is unchanged."
        ),
    }


def _consume_stream(stream: Any, t0: float) -> Dict[str, Any]:
    parts: List[str] = []
    ttft: Optional[float] = None
    usage: Dict[str, Any] = {}
    finish_reason: Optional[str] = None
    model_returned: Optional[str] = None
    provider_meta: Dict[str, Any] = {}
    chunk_ids: List[str] = []

    for chunk in stream:
        mid = getattr(chunk, "model", None)
        if mid:
            model_returned = str(mid)
        cid = getattr(chunk, "id", None)
        if cid:
            chunk_ids.append(str(cid))
        created = getattr(chunk, "created", None)
        fingerprint = getattr(chunk, "system_fingerprint", None)
        if created is not None:
            provider_meta["created"] = created
        if fingerprint:
            provider_meta["system_fingerprint"] = fingerprint

        if getattr(chunk, "usage", None) is not None:
            u = chunk.usage
            usage = {
                "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
            }
            # Preserve nested usage details when present (cached tokens, etc.)
            details = getattr(u, "prompt_tokens_details", None)
            if details is not None:
                try:
                    usage["prompt_tokens_details"] = (
                        details.model_dump()
                        if hasattr(details, "model_dump")
                        else dict(details)
                    )
                except Exception:
                    usage["prompt_tokens_details"] = str(details)
            cdetails = getattr(u, "completion_tokens_details", None)
            if cdetails is not None:
                try:
                    usage["completion_tokens_details"] = (
                        cdetails.model_dump()
                        if hasattr(cdetails, "model_dump")
                        else dict(cdetails)
                    )
                except Exception:
                    usage["completion_tokens_details"] = str(cdetails)

        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice0 = choices[0]
        fr = getattr(choice0, "finish_reason", None)
        if fr:
            finish_reason = str(fr)
        delta = getattr(choice0, "delta", None)
        text = getattr(delta, "content", None) if delta is not None else None
        if text:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000.0
            parts.append(text)

    if chunk_ids:
        provider_meta["stream_chunk_ids_sample"] = chunk_ids[:3]
        provider_meta["stream_chunk_count"] = len(chunk_ids)

    return {
        "answer": "".join(parts),
        "ttft_ms": ttft,
        "usage": usage,
        "finish_reason": finish_reason,
        "model_returned": model_returned,
        "provider_metadata": provider_meta,
        "latency_ms": (time.perf_counter() - t0) * 1000.0,
    }


def _finalize_success(
    *,
    result: ModelRunResult,
    model: str,
    messages: List[Dict[str, str]],
    consumed: Dict[str, Any],
    query: str,
    context_tokens: int,
    retrieval_hits: int,
    input_verification: Optional[Dict[str, Any]],
) -> ModelRunResult:
    answer = consumed["answer"]
    usage = consumed.get("usage") or {}
    latency_ms = float(consumed["latency_ms"])

    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or 0)
    if prompt_tokens <= 0:
        prompt_blob = "\n".join(m.get("content") or "" for m in messages)
        prompt_tokens = _estimate_tokens_fallback(prompt_blob)
        usage["prompt_tokens_source"] = "heuristic_fallback"
    else:
        usage["prompt_tokens_source"] = "api"
    if completion_tokens <= 0:
        completion_tokens = _estimate_tokens_fallback(answer)
        usage["completion_tokens_source"] = "heuristic_fallback"
    else:
        usage["completion_tokens_source"] = "api"
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    result.ok = True
    result.model_requested = model
    result.model_returned = consumed.get("model_returned") or model
    result.finish_reason = consumed.get("finish_reason")
    result.answer = answer
    result.latency_ms = latency_ms
    result.ttft_ms = consumed.get("ttft_ms")
    result.prompt_tokens = prompt_tokens
    result.completion_tokens = completion_tokens
    result.total_tokens = total_tokens
    result.tokens_per_sec = _tokens_per_sec(completion_tokens, latency_ms)
    result.usage_raw = usage
    result.provider_metadata = dict(consumed.get("provider_metadata") or {})
    result.input_verification = dict(input_verification or {})
    result.estimated_api_cost_usd = estimate_api_cost_usd(
        model, prompt_tokens, completion_tokens
    )
    _attach_energy(
        result,
        query=query,
        context_tokens=context_tokens,
        retrieval_hits=retrieval_hits,
    )
    return result


def run_model_streaming(
    *,
    client: Any,
    model: str,
    messages: List[Dict[str, str]],
    query: str,
    context_tokens: int,
    retrieval_hits: int,
    max_tokens: int = 500,
    temperature: float = 0.2,
    timeout_sec: float = 120.0,
    input_verification: Optional[Dict[str, Any]] = None,
) -> ModelRunResult:
    """
    Stream a completion so TTFT can be measured. Collect usage / finish_reason
    / model id from the stream when the API provides them.
    """
    result = ModelRunResult(model=model, ok=False, model_requested=model)
    result.input_verification = dict(input_verification or {})
    t0 = time.perf_counter()

    try:
        kwargs = _completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_sec=timeout_sec,
            use_max_completion_tokens=True,
        )
        try:
            stream = client.chat.completions.create(
                **kwargs, stream_options={"include_usage": True}
            )
        except TypeError:
            stream = client.chat.completions.create(**kwargs)
        consumed = _consume_stream(stream, t0)
        out = _finalize_success(
            result=result,
            model=model,
            messages=messages,
            consumed=consumed,
            query=query,
            context_tokens=context_tokens,
            retrieval_hits=retrieval_hits,
            input_verification=input_verification,
        )
        out.provider_metadata["temperature_sent"] = kwargs.get("temperature")
        return out
    except TypeError:
        return run_model_streaming_legacy(
            client=client,
            model=model,
            messages=messages,
            query=query,
            context_tokens=context_tokens,
            retrieval_hits=retrieval_hits,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_sec=timeout_sec,
            input_verification=input_verification,
        )
    except Exception as e:
        result.error = str(e)
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
        return result


def run_model_streaming_legacy(
    *,
    client: Any,
    model: str,
    messages: List[Dict[str, str]],
    query: str,
    context_tokens: int,
    retrieval_hits: int,
    max_tokens: int = 500,
    temperature: float = 0.2,
    timeout_sec: float = 120.0,
    input_verification: Optional[Dict[str, Any]] = None,
) -> ModelRunResult:
    """Fallback path using max_tokens (older OpenAI SDK parameter name)."""
    result = ModelRunResult(model=model, ok=False, model_requested=model)
    result.input_verification = dict(input_verification or {})
    t0 = time.perf_counter()

    try:
        kwargs = _completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_sec=timeout_sec,
            use_max_completion_tokens=False,
        )
        try:
            stream = client.chat.completions.create(
                **kwargs, stream_options={"include_usage": True}
            )
        except TypeError:
            stream = client.chat.completions.create(**kwargs)

        consumed = _consume_stream(stream, t0)
        out = _finalize_success(
            result=result,
            model=model,
            messages=messages,
            consumed=consumed,
            query=query,
            context_tokens=context_tokens,
            retrieval_hits=retrieval_hits,
            input_verification=input_verification,
        )
        out.provider_metadata["temperature_sent"] = kwargs.get("temperature")
        return out
    except Exception as e:
        result.error = str(e)
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
        return result
