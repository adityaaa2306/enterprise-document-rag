"""
Pre-flight consistency checks so every model receives identical inputs.

Abort the benchmark if frozen identity drifts before a model call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from src.eval.gpt_benchmark.freeze import FrozenBenchmarkInput, hash_context, hash_prompt


class BenchmarkConsistencyError(RuntimeError):
    """Raised when a model would receive non-identical frozen inputs."""


@dataclass(frozen=True)
class FrozenIdentity:
    document_id: str
    context_hash: str
    prompt_hash: str
    chunk_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "document_id": self.document_id,
            "context_hash": self.context_hash,
            "prompt_hash": self.prompt_hash,
            "chunk_count": self.chunk_count,
        }


def identity_from_frozen(frozen: FrozenBenchmarkInput) -> FrozenIdentity:
    return FrozenIdentity(
        document_id=str(frozen.document_id),
        context_hash=str(frozen.context_hash),
        prompt_hash=str(frozen.prompt_hash),
        chunk_count=int(frozen.chunk_count),
    )


def _messages_system_user(messages: Sequence[Dict[str, str]]) -> tuple[str, str]:
    system = ""
    user = ""
    for m in messages:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "system" and not system:
            system = content
        elif role == "user" and not user:
            user = content
    return system, user


def verify_frozen_artifact(frozen: FrozenBenchmarkInput) -> FrozenIdentity:
    """
    Recompute hashes from stored fields and abort if the frozen artifact
    is internally inconsistent.
    """
    recomputed_ctx = hash_context(frozen.context_text)
    if recomputed_ctx != frozen.context_hash:
        raise BenchmarkConsistencyError(
            f"context_hash mismatch: stored={frozen.context_hash} "
            f"recomputed={recomputed_ctx}"
        )

    recomputed_prompt = hash_prompt(frozen.system_prompt, frozen.user_prompt)
    if recomputed_prompt != frozen.prompt_hash:
        raise BenchmarkConsistencyError(
            f"prompt_hash mismatch: stored={frozen.prompt_hash} "
            f"recomputed={recomputed_prompt}"
        )

    if frozen.messages != [
        {"role": "system", "content": frozen.system_prompt},
        {"role": "user", "content": frozen.user_prompt},
    ]:
        raise BenchmarkConsistencyError(
            "Frozen messages do not match stored system/user prompts"
        )

    if int(frozen.chunk_count) != len(frozen.passage_chunk_ids):
        raise BenchmarkConsistencyError(
            f"chunk_count mismatch: stored={frozen.chunk_count} "
            f"ids={len(frozen.passage_chunk_ids)}"
        )

    return identity_from_frozen(frozen)


def assert_identical_model_inputs(
    *,
    expected: FrozenIdentity,
    document_id: str,
    messages: List[Dict[str, str]],
    context_text: str,
    chunk_count: int,
    model: str,
    prompt_version: Optional[str] = None,
) -> Dict[str, object]:
    """
    Verify the exact inputs about to be sent to ``model`` match the freeze.

    Called immediately before every model invocation.
    """
    actual_ctx = hash_context(context_text)
    system, user = _messages_system_user(messages)
    actual_prompt = hash_prompt(system, user, prompt_version=prompt_version)
    actual_doc = str(document_id)
    actual_chunks = int(chunk_count)

    failures: List[str] = []
    if actual_doc != expected.document_id:
        failures.append(
            f"document_id expected={expected.document_id!r} actual={actual_doc!r}"
        )
    if actual_ctx != expected.context_hash:
        failures.append(
            f"context_hash expected={expected.context_hash} actual={actual_ctx}"
        )
    if actual_prompt != expected.prompt_hash:
        failures.append(
            f"prompt_hash expected={expected.prompt_hash} actual={actual_prompt}"
        )
    if actual_chunks != expected.chunk_count:
        failures.append(
            f"chunk_count expected={expected.chunk_count} actual={actual_chunks}"
        )

    if failures:
        raise BenchmarkConsistencyError(
            f"Aborting before model={model!r}: inputs are not identical. "
            + "; ".join(failures)
        )

    return {
        "verified": True,
        "model": model,
        **expected.to_dict(),
    }
