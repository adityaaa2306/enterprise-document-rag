"""
Developer-only FastAPI router for GPT benchmarking.

Mounted ONLY when ENABLE_GPT_BENCHMARK=true. Requires header:
  X-Benchmark-Token: <BENCHMARK_ADMIN_TOKEN>

Never exposed to the normal UI. Prefer the CLI (``python run_benchmark.py``).
"""
from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/dev/benchmark", tags=["dev-benchmark"])


class GptBenchmarkRequest(BaseModel):
    document_id: Optional[str] = None
    filename: Optional[str] = None
    suite: str = Field(default="smoke", pattern="^(smoke|full)$")
    models: Optional[List[str]] = None
    max_tokens: int = Field(default=500, ge=16, le=4000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    dry_run: bool = False
    limit: Optional[int] = Field(default=None, ge=1, le=50)


def _require_benchmark_token(token: Optional[str]) -> None:
    expected = (os.environ.get("BENCHMARK_ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "BENCHMARK_ADMIN_TOKEN is not configured. "
                "Set it in backend/.env to enable the developer benchmark endpoint."
            ),
        )
    if not token or token.strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid benchmark admin token.")


@router.post("/gpt")
def run_gpt_benchmark(
    body: GptBenchmarkRequest,
    x_benchmark_token: Optional[str] = Header(default=None, alias="X-Benchmark-Token"),
):
    """
    Explicit developer trigger for offline GPT benchmarks.

    Disabled unless ENABLE_GPT_BENCHMARK=true (router not mounted otherwise).
    """
    _require_benchmark_token(x_benchmark_token)

    from src.eval.gpt_benchmark.questions import questions_for_suite
    from src.eval.gpt_benchmark.runner import run_benchmark

    questions = questions_for_suite(body.suite)
    if body.limit is not None:
        questions = questions[: body.limit]

    try:
        payload = run_benchmark(
            document_id=body.document_id,
            filename=body.filename,
            suite=body.suite,
            models=body.models,
            questions=questions,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            dry_run=body.dry_run,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "status": "ok",
        "summary": payload.get("summary"),
        "metadata": payload.get("metadata"),
        # Omit full answer bodies from HTTP response to keep payloads small;
        # complete JSON is on disk under benchmark_results/.
        "questions_count": len(payload.get("questions") or []),
    }
