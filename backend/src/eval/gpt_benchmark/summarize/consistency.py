"""Consistency helpers for frozen summarization inputs."""
from __future__ import annotations

from src.eval.gpt_benchmark.consistency import (
    BenchmarkConsistencyError,
    FrozenIdentity,
)
from src.eval.gpt_benchmark.freeze import hash_context, hash_prompt
from src.eval.gpt_benchmark.summarize.freeze import FrozenSummarizationInput


def identity_from_summarization_frozen(
    frozen: FrozenSummarizationInput,
) -> FrozenIdentity:
    return FrozenIdentity(
        document_id=str(frozen.document_id),
        context_hash=str(frozen.context_hash),
        prompt_hash=str(frozen.prompt_hash),
        chunk_count=int(frozen.chunk_count),
    )


def verify_frozen_summarization(
    frozen: FrozenSummarizationInput,
) -> FrozenIdentity:
    recomputed_ctx = hash_context(frozen.document_text)
    if recomputed_ctx != frozen.context_hash:
        raise BenchmarkConsistencyError(
            f"document context_hash mismatch: stored={frozen.context_hash} "
            f"recomputed={recomputed_ctx}"
        )

    recomputed_prompt = hash_prompt(
        frozen.system_prompt,
        frozen.user_prompt,
        prompt_version=frozen.prompt_version,
    )
    if recomputed_prompt != frozen.prompt_hash:
        raise BenchmarkConsistencyError(
            f"summarization prompt_hash mismatch: stored={frozen.prompt_hash} "
            f"recomputed={recomputed_prompt}"
        )

    if frozen.messages != [
        {"role": "system", "content": frozen.system_prompt},
        {"role": "user", "content": frozen.user_prompt},
    ]:
        raise BenchmarkConsistencyError(
            "Frozen summarization messages do not match stored system/user prompts"
        )

    if int(frozen.chunk_count) != len(frozen.chunk_boundaries):
        raise BenchmarkConsistencyError(
            f"chunk_count mismatch: stored={frozen.chunk_count} "
            f"boundaries={len(frozen.chunk_boundaries)}"
        )

    return identity_from_summarization_frozen(frozen)
