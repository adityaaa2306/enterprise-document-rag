"""
Quality Validation Agent

Evaluates faithfulness, hallucination risk, coverage, contradictions, confidence.
Escalation is decided by the orchestrator — never for carbon reasons.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from src.agents import models
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-zA-Z]{3,}", (text or "").lower()))


def _coverage(source: str, summary: str) -> float:
    src = _tokens(source)
    sm = _tokens(summary)
    if not sm:
        return 0.0
    if not src:
        return 0.5
    # Fraction of summary content tokens that appear in source (groundedness proxy)
    grounded = len(sm & src) / max(len(sm), 1)
    # Also reward covering distinctive source terms
    rare = {t for t in src if len(t) >= 6}
    cover_src = len(sm & rare) / max(len(rare), 1) if rare else grounded
    return max(0.0, min(1.0, 0.6 * grounded + 0.4 * cover_src))


def _hallucination_rate(source: str, summary: str) -> float:
    src = _tokens(source)
    sm = _tokens(summary)
    if not sm:
        return 1.0
    novel = sm - src
    # Ignore very common words already filtered by length; remaining novel = risk
    return max(0.0, min(1.0, len(novel) / max(len(sm), 1)))


def _contradiction_rate(source: str, summary: str) -> float:
    # Lightweight cue: negation flips between source and summary on shared subjects
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
            s_neg = any(n in s_low for n in neg)
            m_neg = any(n in m_low for n in neg)
            # crude: if one side heavily negated lexicon near term — skip deep parse
            if (" not " + term in m_low or term + " not" in m_low) and term in s_low:
                if " not " + term not in s_low:
                    hits += 1
    if checks == 0:
        return 0.0
    return max(0.0, min(1.0, hits / checks))


def validate_pair(source: str, summary: str) -> ValidationVerdict:
    codes: List[str] = []

    # Faithfulness via existing NLI checker when available
    nli_ok = models.run_accuracy_check(source, summary)
    faithfulness = 0.85 if nli_ok else 0.35

    coverage = _coverage(source, summary)
    hallu = _hallucination_rate(source, summary)
    contra = _contradiction_rate(source, summary)

    conf = (
        0.40 * faithfulness
        + 0.25 * coverage
        + 0.20 * (1.0 - hallu)
        + 0.15 * (1.0 - contra)
    )

    tau = settings.QVA_CONFIDENCE_THRESHOLD
    faith_min = settings.QVA_FAITHFULNESS_MIN
    hallu_max = settings.QVA_HALLUCINATION_MAX
    contra_max = settings.QVA_CONTRADICTION_MAX

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

    passed = (
        faithfulness >= faith_min
        and hallu <= hallu_max
        and contra <= contra_max
        and conf >= tau
    )

    return ValidationVerdict(
        passed=passed,
        confidence=round(conf, 4),
        faithfulness=round(faithfulness, 4),
        coverage=round(coverage, 4),
        hallucination_rate=round(hallu, 4),
        contradiction_rate=round(contra, 4),
        codes=codes,
        details={"nli_ok": nli_ok},
    )


def validate_chunks(chunks: List[Any], summaries: List[str]) -> ValidationVerdict:
    """Aggregate chunk-level validation into one verdict."""
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
    verdicts = []
    for i in range(pair_count):
        content = chunks[i].content if hasattr(chunks[i], "content") else str(chunks[i])
        verdicts.append(validate_pair(content, summaries[i]))

    fail_ratio = sum(1 for v in verdicts if not v.passed) / len(verdicts)
    avg_conf = sum(v.confidence for v in verdicts) / len(verdicts)
    avg_faith = sum(v.faithfulness for v in verdicts) / len(verdicts)
    avg_cover = sum(v.coverage for v in verdicts) / len(verdicts)
    avg_hallu = sum(v.hallucination_rate for v in verdicts) / len(verdicts)
    avg_contra = sum(v.contradiction_rate for v in verdicts) / len(verdicts)

    codes: List[str] = []
    if fail_ratio > 0.25:
        codes.append("chunk_fail_ratio_high")
    if avg_conf < settings.QVA_CONFIDENCE_THRESHOLD:
        codes.append("aggregate_low_confidence")

    # Pass if most chunks OK and aggregate confidence OK
    passed = fail_ratio <= 0.25 and avg_conf >= settings.QVA_CONFIDENCE_THRESHOLD

    return ValidationVerdict(
        passed=passed,
        confidence=round(avg_conf, 4),
        faithfulness=round(avg_faith, 4),
        coverage=round(avg_cover, 4),
        hallucination_rate=round(avg_hallu, 4),
        contradiction_rate=round(avg_contra, 4),
        codes=codes,
        details={
            "chunk_count": pair_count,
            "fail_ratio": round(fail_ratio, 4),
            "failed_indices": [i for i, v in enumerate(verdicts) if not v.passed],
        },
    )


def validate_final(source_summaries: List[str], final_summary: str) -> ValidationVerdict:
    source = "\n\n".join(source_summaries)
    return validate_pair(source, final_summary)
