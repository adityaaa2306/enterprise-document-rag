"""
Feature Extraction Agent

Extracts capability-relevant signals. Document type and domain risk use a
lightweight NIM classifier when available; structural signals come from
parser metadata (no LLM). Heuristic fallbacks when NIM is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.agents import models

log = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    "research_paper",
    "legal_contract",
    "medical_report",
    "financial_statement",
    "regulatory_document",
    "technical_documentation",
    "meeting_minutes",
    "resume",
    "business_report",
    "invoice",
    "general_text",
]

DOMAIN_LABELS = ["general", "legal", "medical", "financial", "regulatory", "technical"]
RISK_LEVELS = ["general", "low", "medium", "high"]


def _chunk_texts(chunks: List[Any]) -> List[str]:
    texts = []
    for c in chunks:
        if hasattr(c, "content"):
            texts.append(c.content or "")
        elif isinstance(c, dict):
            texts.append(c.get("content") or c.get("text") or "")
        else:
            texts.append(str(c))
    return texts


def _chunk_types(chunks: List[Any]) -> List[str]:
    types = []
    for c in chunks:
        if hasattr(c, "type"):
            types.append(str(c.type))
        elif isinstance(c, dict):
            types.append(str(c.get("type", "Text")))
        else:
            types.append("Text")
    return types


def _sample_text(texts: List[str], max_chars: int = 3500) -> str:
    joined = "\n\n".join(texts)
    return joined[:max_chars]


# ---------------------------------------------------------------------------
# Structural profile (parser-driven, no LLM)
# ---------------------------------------------------------------------------

def structural_profile(chunks: List[Any], triage_meta: Optional[Dict] = None) -> Dict[str, Any]:
    triage_meta = triage_meta or {}
    texts = _chunk_texts(chunks)
    types = _chunk_types(chunks)
    n = max(len(chunks), 1)

    table_n = sum(1 for t in types if t == "Table")
    list_n = sum(1 for t in types if t == "List")
    title_n = sum(1 for t in types if t == "Title")

    table_density = table_n / n
    # Heuristic image/chart proxies from content markers
    image_hits = sum(1 for t in texts if re.search(r"\[image|figure\s+\d|chart\s+\d", t, re.I))
    chart_hits = sum(1 for t in texts if re.search(r"\b(chart|graph|plot)\b", t, re.I))
    eq_hits = sum(1 for t in texts if re.search(r"(\$\$|\\begin\{equation\}|∑|∫|=.*\+.*)", t))
    code_hits = sum(1 for t in texts if re.search(r"```|def |class |function |#include", t))

    strategy = triage_meta.get("strategy", settings.TRIAGE_STRATEGY)
    scanned = triage_meta.get("scanned", strategy == "hi_res")
    ocr_confidence = float(triage_meta.get("ocr_confidence", 0.85 if strategy == "fast" else 0.55))

    multi_column = bool(triage_meta.get("multi_column", False))
    layout_complexity = float(triage_meta.get("layout_complexity", 0.0))
    if table_density > 0.15:
        layout_complexity = max(layout_complexity, 0.5)
    if multi_column:
        layout_complexity = max(layout_complexity, 0.6)
    if scanned:
        layout_complexity = max(layout_complexity, 0.55)

    formatting_quality = 1.0 - min(1.0, (1.0 - ocr_confidence) * 0.8 + table_density * 0.2)

    # Structural difficulty S ∈ [0,1]
    S = (
        0.25 * (1.0 - ocr_confidence)
        + 0.20 * min(1.0, table_density * 3)
        + 0.10 * min(1.0, image_hits / max(n, 1) * 4)
        + 0.10 * min(1.0, chart_hits / max(n, 1) * 4)
        + 0.15 * layout_complexity
        + 0.10 * (1.0 if scanned else 0.0)
        + 0.05 * min(1.0, eq_hits / max(n, 1) * 3)
        + 0.05 * min(1.0, code_hits / max(n, 1) * 3)
    )
    S = max(0.0, min(1.0, S))

    return {
        "ocr_confidence": round(ocr_confidence, 3),
        "table_density": round(table_density, 3),
        "image_density": round(image_hits / n, 3),
        "chart_density": round(chart_hits / n, 3),
        "multi_column": multi_column,
        "layout_complexity": round(layout_complexity, 3),
        "scanned_vs_digital": "scanned" if scanned else "digital",
        "formatting_quality": round(formatting_quality, 3),
        "equation_density": round(eq_hits / n, 3),
        "code_density": round(code_hits / n, 3),
        "structural_score": round(S, 4),
        "table_count": table_n,
        "list_count": list_n,
        "title_count": title_n,
    }


# ---------------------------------------------------------------------------
# Reasoning + coherence (heuristic + optional LLM assist)
# ---------------------------------------------------------------------------

def reasoning_profile(chunks: List[Any]) -> Dict[str, Any]:
    texts = _chunk_texts(chunks)
    sample = _sample_text(texts, 5000).lower()
    n = max(len(chunks), 1)

    abstractive_markers = len(re.findall(
        r"\b(therefore|thus|implies|suggests|overall|in conclusion|we argue|hypothesis)\b",
        sample,
    ))
    contradiction = len(re.findall(
        r"\b(however|whereas|although|contradict|in contrast|on the other hand|despite)\b",
        sample,
    ))
    inference = len(re.findall(
        r"\b(because|due to|leads to|results in|causal|implies that)\b",
        sample,
    ))
    cross_section = len(re.findall(
        r"\b(see section|as discussed|chapter \d|refer to|supra|infra|appendix)\b",
        sample,
    ))
    multi_doc = len(re.findall(r"\b(according to|cited|et al|reference|bibliography)\b", sample))

    # Extractive-friendly if mostly short factual lists/tables
    types = _chunk_types(chunks)
    table_ratio = sum(1 for t in types if t == "Table") / n
    extractive_bias = min(1.0, table_ratio * 1.5 + (0.3 if n < 5 else 0.0))

    R = (
        0.20 * min(1.0, abstractive_markers / 8)
        + 0.15 * (1.0 - extractive_bias)
        + 0.15 * min(1.0, cross_section / 5)
        + 0.15 * min(1.0, contradiction / 5)
        + 0.15 * min(1.0, inference / 6)
        + 0.10 * min(1.0, multi_doc / 6)
        + 0.10 * min(1.0, n / 40)  # mild long-range pressure from many chunks
    )
    R = max(0.05, min(1.0, R))

    return {
        "extractive_bias": round(extractive_bias, 3),
        "abstractive_need": round(min(1.0, abstractive_markers / 8), 3),
        "cross_section_synthesis": round(min(1.0, cross_section / 5), 3),
        "contradiction_signals": contradiction,
        "inference_signals": inference,
        "multi_document_signals": multi_doc,
        "reasoning_score": round(R, 4),
    }


def coherence_profile(chunks: List[Any]) -> Dict[str, Any]:
    texts = _chunk_texts(chunks)
    n = max(len(chunks), 1)
    sample = _sample_text(texts, 6000)

    cross_refs = len(re.findall(
        r"\b(see (section|chapter|fig|table|above|below)|as (noted|mentioned)|refer to)\b",
        sample,
        re.I,
    ))

    # Terminology consistency: Jaccard overlap of top tokens across halves
    def tokens(s: str) -> set:
        return set(re.findall(r"[a-zA-Z]{4,}", s.lower()))

    mid = max(1, len(texts) // 2)
    left = tokens(" ".join(texts[:mid]))
    right = tokens(" ".join(texts[mid:]))
    if left and right:
        jaccard = len(left & right) / max(1, len(left | right))
        term_consistency = jaccard
    else:
        term_consistency = 0.7

    long_range = min(1.0, n / 30 + cross_refs / 10)
    # Coherence *demand* X: high when many chunks + low consistency + many refs
    X = (
        0.35 * min(1.0, n / 25)
        + 0.25 * long_range
        + 0.25 * (1.0 - term_consistency)
        + 0.15 * min(1.0, cross_refs / 8)
    )
    X = max(0.0, min(1.0, X))

    return {
        "chunk_count": n,
        "cross_references": cross_refs,
        "long_range_dependency": round(long_range, 3),
        "terminology_consistency": round(term_consistency, 3),
        "coherence_score": round(X, 4),
    }


# ---------------------------------------------------------------------------
# Document type + domain risk (lightweight LLM classifier)
# ---------------------------------------------------------------------------

def _parse_json_blob(text: str) -> Optional[Dict]:
    text = text.strip()
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def classify_document_llm(sample: str) -> Optional[Dict[str, Any]]:
    """Use Light NIM model as a lightweight classifier (structured JSON)."""
    if models.get_nim_client() is None:
        return None

    timeout_sec = float(
        getattr(settings, "FEATURE_EXTRACTION_LLM_TIMEOUT_SEC", 12.0) or 12.0
    )

    def _invoke() -> Optional[Dict[str, Any]]:
        prompt = f"""Classify this document. Reply with ONLY valid JSON, no markdown:
{{
  "document_type": one of {DOCUMENT_TYPES},
  "domain_label": one of {DOMAIN_LABELS},
  "risk_level": one of {RISK_LEVELS},
  "confidence": 0.0-1.0
}}

Document excerpt:
{sample[:3000]}
"""
        text, _ = models.call_chat_with_fallback(
            settings.light_models(),
            [
                {
                    "role": "system",
                    "content": "You are a document classifier. Output only JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
            max_retries_per_model=1,
        )
        data = _parse_json_blob(text)
        if not data:
            return None
        dtype = data.get("document_type", "general_text")
        if dtype not in DOCUMENT_TYPES:
            dtype = "general_text"
        domain = data.get("domain_label", "general")
        if domain not in DOMAIN_LABELS:
            domain = "general"
        risk = data.get("risk_level", "low")
        if risk not in RISK_LEVELS:
            risk = "low"
        # Enforce high risk for sensitive domains
        if domain in ("legal", "medical", "financial", "regulatory"):
            risk = "high"
        return {
            "document_type": dtype,
            "domain_label": domain,
            "risk_level": risk,
            "classifier_confidence": float(data.get("confidence", 0.7)),
            "classifier_method": "nim_light_llm",
        }

    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_invoke)
            try:
                return fut.result(timeout=timeout_sec)
            except FuturesTimeout:
                log.warning(
                    "LLM document classifier soft-timeout after %.1fs → heuristic fallback",
                    timeout_sec,
                )
                return None
    except Exception as e:
        # Timeouts / 5xx / connection errors are expected under NIM load —
        # never abort the pipeline for optional classification metadata.
        if models.is_transient_nim_error(e):
            log.warning(f"LLM document classifier transient failure: {e}")
        else:
            log.warning(f"LLM document classifier failed: {e}")
        return None



def classify_document_heuristic(sample: str, structural: Dict, reasoning: Dict) -> Dict[str, Any]:
    """
    Structure- and discourse-aware fallback (not keyword-only).
    Uses layout + discourse density patterns as a weak classifier.
    """
    s = sample.lower()
    # Discourse / layout signatures
    scores = {t: 0.0 for t in DOCUMENT_TYPES}

    if structural.get("table_density", 0) > 0.2 and re.search(r"\b(total|amount|balance|invoice)\b", s):
        scores["invoice"] += 0.5
        scores["financial_statement"] += 0.4
    if reasoning.get("multi_document_signals", 0) > 3 and re.search(r"\babstract|references\b", s):
        scores["research_paper"] += 0.6
    if structural.get("title_count", 0) >= 3 and re.search(r"\bagenda|minutes|attendees\b", s):
        scores["meeting_minutes"] += 0.5
    if re.search(r"\bexperience|education|skills\b", s) and len(s) < 8000:
        scores["resume"] += 0.4
    if re.search(r"\bwhereas|hereinafter|party|agreement|indemnif", s):
        scores["legal_contract"] += 0.7
    if re.search(r"\bpatient|diagnosis|clinical|dosage|mg/dl\b", s):
        scores["medical_report"] += 0.7
    if re.search(r"\bsec\.|regulation|compliance|cfr\b", s):
        scores["regulatory_document"] += 0.6
    if re.search(r"\brevenue|ebitda|balance sheet|10-k|fiscal\b", s):
        scores["financial_statement"] += 0.6
    if re.search(r"\bapi|endpoint|configuration|install\b", s):
        scores["technical_documentation"] += 0.4

    best = max(scores, key=scores.get)
    if scores[best] < 0.35:
        best = "general_text"
        domain, risk = "general", "low"
    elif best in ("legal_contract",):
        domain, risk = "legal", "high"
    elif best in ("medical_report",):
        domain, risk = "medical", "high"
    elif best in ("financial_statement", "invoice"):
        domain, risk = "financial", "high"
    elif best in ("regulatory_document",):
        domain, risk = "regulatory", "high"
    elif best in ("technical_documentation", "research_paper"):
        domain, risk = "technical", "medium"
    else:
        domain, risk = "general", "low"

    return {
        "document_type": best,
        "domain_label": domain,
        "risk_level": risk,
        "classifier_confidence": round(min(0.85, 0.4 + scores[best]), 3),
        "classifier_method": "heuristic_fallback",
    }


# ---------------------------------------------------------------------------
# Retrieval confidence (pre-index probe via self-similarity of chunks)
# ---------------------------------------------------------------------------

def retrieval_confidence_probe(chunks: List[Any]) -> Dict[str, Any]:
    """
    Before full indexing, estimate retrieval difficulty via embedding
    self-similarity of a sample of chunks. Low separation → low ρ.
    Falls back to structural heuristic if embeddings unavailable.
    """
    texts = [t for t in _chunk_texts(chunks) if t.strip()]
    if len(texts) < 2:
        return {"retrieval_confidence": 0.75, "retrieval_method": "trivial"}

    sample = texts[: min(8, len(texts))]
    try:
        if models.get_embedding_model():
            vectors = models.embed_texts(sample)

            def cosine(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                na = sum(x * x for x in a) ** 0.5
                nb = sum(y * y for y in b) ** 0.5
                return dot / max(na * nb, 1e-9)

            sims = []
            for i in range(len(vectors)):
                for j in range(i + 1, len(vectors)):
                    sims.append(cosine(vectors[i], vectors[j]))
            avg_sim = sum(sims) / max(len(sims), 1)
            # High avg similarity → chunks hard to distinguish → lower ρ
            # Low avg similarity → distinctive chunks → higher ρ
            rho = max(0.15, min(0.95, 1.0 - (avg_sim - 0.2) * 1.2))
            return {
                "retrieval_confidence": round(rho, 4),
                "chunk_avg_similarity": round(avg_sim, 4),
                "retrieval_method": "embedding_probe",
            }
    except Exception as e:
        log.warning(f"Retrieval probe failed: {e}")

    # Heuristic: many short similar-looking chunks → lower confidence
    avg_len = sum(len(t) for t in sample) / len(sample)
    rho = 0.55 if avg_len < 200 else 0.7
    return {"retrieval_confidence": rho, "retrieval_method": "heuristic"}


# ---------------------------------------------------------------------------
# Carbon + runtime context
# ---------------------------------------------------------------------------

def carbon_context() -> Dict[str, Any]:
    intensity = settings.LOCAL_GRID_INTENSITY
    return {
        "grid_carbon_intensity_gco2_kwh": intensity,
        "compute_region": "local_simulated",
        "baseline_grid_intensity": settings.BASELINE_GRID_INTENSITY,
        "carbon_note": "Optimization parameter only; never overrides capability floors",
    }


def runtime_constraints() -> Dict[str, Any]:
    nim_ok = models.get_nim_client() is not None
    return {
        "nim_available": nim_ok,
        "api_health": "healthy" if nim_ok else "degraded",
        "estimated_latency_budget_ms": 8000 if nim_ok else 15000,
        "rate_limit_state": "ok",
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def default_features(
    chunks: Optional[List[Any]] = None,
    triage_meta: Optional[Dict[str, Any]] = None,
    *,
    reason: str = "fallback",
) -> Dict[str, Any]:
    """
    Safe default metadata when LLM/embedding feature extraction fails.
    Keeps CRE + routing functional without aborting the pipeline.
    """
    chunks = chunks or []
    triage_meta = triage_meta or {}
    try:
        structural = structural_profile(chunks, triage_meta) if chunks else {
            "structural_score": 0.5,
            "table_density": 0.0,
            "title_count": 0,
            "avg_chunk_chars": 0,
        }
        reasoning = reasoning_profile(chunks) if chunks else {
            "reasoning_score": 0.5,
            "multi_document_signals": 0,
        }
        coherence = coherence_profile(chunks) if chunks else {"coherence_score": 0.5}
        classification = classify_document_heuristic(
            _sample_text(_chunk_texts(chunks)) if chunks else "",
            structural,
            reasoning,
        )
    except Exception:
        structural = {"structural_score": 0.5, "table_density": 0.0, "title_count": 0, "avg_chunk_chars": 0}
        reasoning = {"reasoning_score": 0.5, "multi_document_signals": 0}
        coherence = {"coherence_score": 0.5}
        classification = {
            "document_type": "general_text",
            "domain_label": "general",
            "risk_level": "low",
            "classifier_confidence": 0.3,
            "classifier_method": "default_metadata",
        }

    classification = {
        **classification,
        "classifier_method": f"default_metadata:{reason}",
    }
    return {
        **classification,
        **structural,
        **reasoning,
        **coherence,
        "retrieval_confidence": 0.6,
        "retrieval_method": "default",
        "carbon": carbon_context(),
        "runtime": runtime_constraints(),
        "chunk_count": len(chunks),
    }


def extract_features(
    chunks: List[Any],
    triage_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Full feature vector for CRE + Router.

    Feature extraction is optional metadata: NVIDIA classifier / embedding probe
    failures fall back to heuristics / defaults and never abort the job.
    """
    triage_meta = triage_meta or {}
    optional = bool(getattr(settings, "FEATURE_EXTRACTION_OPTIONAL", True))

    try:
        texts = _chunk_texts(chunks)
        sample = _sample_text(texts)

        structural = structural_profile(chunks, triage_meta)
        reasoning = reasoning_profile(chunks)
        coherence = coherence_profile(chunks)

        try:
            retrieval = retrieval_confidence_probe(chunks)
        except Exception as e:
            log.warning(
                "feature extraction: retrieval probe failed (%s) → heuristic defaults",
                e,
            )
            retrieval = {"retrieval_confidence": 0.6, "retrieval_method": "heuristic_after_error"}

        classification = None
        try:
            classification = classify_document_llm(sample)
            if classification:
                log.info(
                    "feature extraction: LLM classification ok method=%s type=%s",
                    classification.get("classifier_method"),
                    classification.get("document_type"),
                )
        except Exception as e:
            log.warning(
                "feature extraction: LLM classification failed (%s) → heuristic fallback",
                e,
            )
            classification = None

        if not classification:
            log.info("feature extraction: using heuristic / default metadata")
            classification = classify_document_heuristic(sample, structural, reasoning)

        features = {
            **classification,
            **structural,
            **reasoning,
            **coherence,
            **retrieval,
            "carbon": carbon_context(),
            "runtime": runtime_constraints(),
            "chunk_count": len(chunks),
        }
        log.info(
            f"FEA: type={features['document_type']} domain={features['domain_label']}/"
            f"{features['risk_level']} R={features['reasoning_score']} "
            f"S={features['structural_score']} X={features['coherence_score']} "
            f"ρ={features['retrieval_confidence']} via {features['classifier_method']}"
        )
        return features
    except Exception as e:
        if not optional:
            raise
        log.exception(
            "feature extraction: unexpected failure (%s) → default metadata; pipeline continues",
            e,
        )
        return default_features(chunks, triage_meta, reason=type(e).__name__)
