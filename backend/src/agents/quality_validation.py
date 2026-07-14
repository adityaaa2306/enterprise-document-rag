"""
Quality Validation Agent

Evaluates faithfulness, hallucination risk, coverage, contradictions, confidence,
semantic similarity (embedding cosine when available), entity retention,
compression ratio, and redundancy.

Escalation is decided by the orchestrator — never for carbon reasons.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence

from src.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class ValidationVerdict:
    passed: bool
    confidence: float
    faithfulness: float
    coverage: float
    hallucination_rate: float
    contradiction_rate: float
    codes: List[str]
    details: Dict[str, Any]
    semantic_similarity: float = 0.0
    entity_retention: float = 0.0
    compression_ratio: float = 0.0
    redundancy: float = 0.0
    readability: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-zA-Z]{3,}", (text or "").lower()))


def _entities(text: str) -> set:
    return set(re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z]{2,})\b", text or ""))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return float(dot / (na * nb))


def _coverage(source: str, summary: str) -> float:
    src = _tokens(source)
    sm = _tokens(summary)
    if not sm:
        return 0.0
    if not src:
        return 0.5
    grounded = len(sm & src) / max(len(sm), 1)
    rare = {t for t in src if len(t) >= 6}
    cover_src = len(sm & rare) / max(len(rare), 1) if rare else grounded
    return max(0.0, min(1.0, 0.6 * grounded + 0.4 * cover_src))


def _hallucination_rate(source: str, summary: str) -> float:
    src = _tokens(source)
    sm = _tokens(summary)
    if not sm:
        return 1.0
    novel = sm - src
    return max(0.0, min(1.0, len(novel) / max(len(sm), 1)))


def _contradiction_rate(source: str, summary: str) -> float:
    neg = (" not ", " no ", " never ", " without ", "n't")
    s_low = f" {source.lower()} "
    m_low = f" {summary.lower()} "
    hits = 0
    checks = 0
    for term in list(_tokens(summary))[:40]:
        if len(term) < 5:
            continue
        if term in s_low and term in m_low:
            checks += 1
            if (" not " + term in m_low or term + " not" in m_low) and term in s_low:
                if " not " + term not in s_low:
                    hits += 1
    if checks == 0:
        return 0.0
    return max(0.0, min(1.0, hits / checks))


def _entity_retention(source: str, summary: str) -> float:
    src_e = _entities(source)
    if not src_e:
        return 1.0
    sm_e = _entities(summary)
    return len(src_e & sm_e) / max(1, len(src_e))


def _compression_ratio(source: str, summary: str) -> float:
    s_len = max(1, len(source or ""))
    m_len = max(0, len(summary or ""))
    return max(0.0, min(1.0, m_len / s_len))


def _redundancy(summary: str) -> float:
    sents = [s.strip() for s in re.split(r"[.!?]\s+", summary or "") if s.strip()]
    if len(sents) < 2:
        return 0.0
    overlaps = 0
    checks = 0
    for i in range(len(sents) - 1):
        a = _tokens(sents[i])
        b = _tokens(sents[i + 1])
        if not a or not b:
            continue
        checks += 1
        if len(a & b) / max(1, len(a | b)) > 0.7:
            overlaps += 1
    if checks == 0:
        return 0.0
    return overlaps / checks


def _readability(summary: str) -> float:
    words = re.findall(r"\S+", summary or "")
    if not words:
        return 0.0
    avg = sum(len(w) for w in words) / len(words)
    # Prefer moderate word length
    return max(0.0, min(1.0, 1.0 - abs(avg - 5.5) / 8.0))


def validate_pair(
    source: str,
    summary: str,
    *,
    source_embedding: Optional[Sequence[float]] = None,
    summary_embedding: Optional[Sequence[float]] = None,
    confidence_threshold: Optional[float] = None,
) -> ValidationVerdict:
    codes: List[str] = []

    coverage = _coverage(source, summary)
    hallu = _hallucination_rate(source, summary)
    contra = _contradiction_rate(source, summary)
    faithfulness = max(0.0, min(1.0, 0.70 * coverage + 0.30 * (1.0 - hallu)))
    entity_ret = _entity_retention(source, summary)
    compression = _compression_ratio(source, summary)
    redundancy = _redundancy(summary)
    readability = _readability(summary)

    semantic = 0.0
    if source_embedding is not None and summary_embedding is not None:
        semantic = _cosine(list(source_embedding), list(summary_embedding))
    else:
        # Lexical Jaccard as weak semantic proxy
        a, b = _tokens(source), _tokens(summary)
        semantic = (len(a & b) / max(1, len(a | b))) if a or b else 0.0

    src_nums = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", source or ""))
    sm_nums = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", summary or ""))
    if src_nums:
        num_consistency = len(src_nums & sm_nums) / max(1, min(8, len(src_nums)))
        num_consistency = max(0.0, min(1.0, num_consistency))
    else:
        num_consistency = 1.0
    fact_consistency = max(
        0.0,
        min(1.0, 0.5 * (1.0 - hallu) + 0.3 * (1.0 - contra) + 0.2 * num_consistency),
    )

    conf = (
        0.26 * faithfulness
        + 0.16 * coverage
        + 0.12 * (1.0 - hallu)
        + 0.08 * (1.0 - contra)
        + 0.14 * semantic
        + 0.10 * entity_ret
        + 0.08 * num_consistency
        + 0.06 * (1.0 - redundancy)
    )

    tau = float(
        confidence_threshold
        if confidence_threshold is not None
        else settings.QVA_CONFIDENCE_THRESHOLD
    )
    faith_min = settings.QVA_FAITHFULNESS_MIN
    hallu_max = settings.QVA_HALLUCINATION_MAX
    contra_max = settings.QVA_CONTRADICTION_MAX
    sem_min = float(getattr(settings, "QVA_SEMANTIC_SIM_MIN", 0.0) or 0.0)
    ent_min = float(getattr(settings, "QVA_ENTITY_RETENTION_MIN", 0.0) or 0.0)

    if faithfulness < faith_min:
        codes.append("low_faithfulness")
    if hallu > hallu_max:
        codes.append("high_hallucination")
    if contra > contra_max:
        codes.append("contradictions")
    if coverage < 0.35:
        codes.append("low_coverage")
    if conf < tau:
        codes.append("low_confidence")
    if sem_min > 0 and semantic < sem_min:
        codes.append("low_semantic_similarity")
    if ent_min > 0 and entity_ret < ent_min and len(_entities(source)) >= 3:
        codes.append("low_entity_retention")
    if num_consistency < 0.25 and len(src_nums) >= 3:
        codes.append("numerical_inconsistency")

    passed = (
        faithfulness >= faith_min
        and hallu <= hallu_max
        and contra <= contra_max
        and conf >= tau
        and (sem_min <= 0 or semantic >= sem_min)
    )

    return ValidationVerdict(
        passed=passed,
        confidence=round(conf, 4),
        faithfulness=round(faithfulness, 4),
        coverage=round(coverage, 4),
        hallucination_rate=round(hallu, 4),
        contradiction_rate=round(contra, 4),
        codes=codes,
        semantic_similarity=round(semantic, 4),
        entity_retention=round(entity_ret, 4),
        compression_ratio=round(compression, 4),
        redundancy=round(redundancy, 4),
        readability=round(readability, 4),
        details={
            "method": "lexical+semantic",
            "nli_ok": None,
            "faithfulness_min": faith_min,
            "hallucination_max": hallu_max,
            "contradiction_max": contra_max,
            "confidence_threshold": tau,
            "semantic_sim_min": sem_min,
            "entity_retention_min": ent_min,
            "quality_estimate": round(conf, 4),
            "fact_consistency": round(fact_consistency, 4),
            "numerical_consistency": round(num_consistency, 4),
        },
    )


def _aggregate_verdicts(
    verdicts: List[ValidationVerdict],
    *,
    pair_count: int,
) -> ValidationVerdict:
    fail_ratio = sum(1 for v in verdicts if not v.passed) / max(len(verdicts), 1)
    avg_conf = sum(v.confidence for v in verdicts) / max(len(verdicts), 1)
    avg_faith = sum(v.faithfulness for v in verdicts) / max(len(verdicts), 1)
    avg_cover = sum(v.coverage for v in verdicts) / max(len(verdicts), 1)
    avg_hallu = sum(v.hallucination_rate for v in verdicts) / max(len(verdicts), 1)
    avg_contra = sum(v.contradiction_rate for v in verdicts) / max(len(verdicts), 1)
    avg_sem = sum(v.semantic_similarity for v in verdicts) / max(len(verdicts), 1)
    avg_ent = sum(v.entity_retention for v in verdicts) / max(len(verdicts), 1)

    codes: List[str] = []
    if fail_ratio > 0.25:
        codes.append("chunk_fail_ratio_high")
    if avg_conf < settings.QVA_CONFIDENCE_THRESHOLD:
        codes.append("aggregate_low_confidence")

    passed = fail_ratio <= 0.25 and avg_conf >= settings.QVA_CONFIDENCE_THRESHOLD

    return ValidationVerdict(
        passed=passed,
        confidence=round(avg_conf, 4),
        faithfulness=round(avg_faith, 4),
        coverage=round(avg_cover, 4),
        hallucination_rate=round(avg_hallu, 4),
        contradiction_rate=round(avg_contra, 4),
        semantic_similarity=round(avg_sem, 4),
        entity_retention=round(avg_ent, 4),
        codes=codes,
        details={
            "chunk_count": pair_count,
            "fail_ratio": round(fail_ratio, 4),
            "failed_indices": [i for i, v in enumerate(verdicts) if not v.passed],
            "chunk_confidences": [round(v.confidence, 4) for v in verdicts],
            "chunk_semantic": [round(v.semantic_similarity, 4) for v in verdicts],
            "pass_rate": round(1.0 - fail_ratio, 4),
        },
    )


def validate_chunks(
    chunks: List[Any],
    summaries: List[str],
    *,
    embeddings: Optional[List[Optional[Sequence[float]]]] = None,
    confidence_threshold: Optional[float] = None,
    only_indices: Optional[List[int]] = None,
    prior_verdicts: Optional[List[Optional[ValidationVerdict]]] = None,
) -> ValidationVerdict:
    """
    Aggregate chunk-level validation into one verdict.

    Parallelizes pair checks. When ``only_indices`` + ``prior_verdicts`` are
    provided, only those indices are revalidated (incremental / escalate path);
    other slots reuse prior results — functionally equivalent to full revalidation
    of unchanged summaries.
    """
    if not chunks or not summaries:
        return ValidationVerdict(
            passed=False,
            confidence=0.0,
            faithfulness=0.0,
            coverage=0.0,
            hallucination_rate=1.0,
            contradiction_rate=0.0,
            codes=["empty_input"],
            details={},
        )

    pair_count = min(len(chunks), len(summaries))
    indices = (
        [i for i in only_indices if 0 <= i < pair_count]
        if only_indices is not None
        else list(range(pair_count))
    )

    def _one(i: int) -> tuple:
        content = chunks[i].content if hasattr(chunks[i], "content") else str(chunks[i])
        emb = embeddings[i] if embeddings and i < len(embeddings) else None
        return i, validate_pair(
            content,
            summaries[i],
            source_embedding=emb,
            summary_embedding=None,
            confidence_threshold=confidence_threshold,
        )

    workers = max(1, int(getattr(settings, "VALIDATE_MAX_WORKERS", 8) or 8))
    results: Dict[int, ValidationVerdict] = {}
    if len(indices) == 1 or workers == 1:
        for i in indices:
            _, v = _one(i)
            results[i] = v
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(workers, len(indices))
        ) as pool:
            for i, v in pool.map(lambda idx: _one(idx), indices):
                results[i] = v

    verdicts: List[ValidationVerdict] = []
    for i in range(pair_count):
        if i in results:
            verdicts.append(results[i])
        elif prior_verdicts and i < len(prior_verdicts) and prior_verdicts[i] is not None:
            verdicts.append(prior_verdicts[i])  # type: ignore[arg-type]
        else:
            # Missing prior — validate this slot
            _, v = _one(i)
            verdicts.append(v)

    out = _aggregate_verdicts(verdicts, pair_count=pair_count)
    out.details["incremental"] = only_indices is not None
    out.details["validated_indices"] = list(indices)
    # Full per-chunk verdicts for incremental reuse (functional equivalence)
    out.details["chunk_verdicts"] = [v.to_dict() for v in verdicts]
    return out


def validate_final(source_summaries: List[str], final_summary: str) -> ValidationVerdict:
    source = "\n\n".join(source_summaries)
    return validate_pair(source, final_summary)
