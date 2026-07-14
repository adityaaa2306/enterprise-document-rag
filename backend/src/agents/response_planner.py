"""
Adaptive response length planner (query-path generation only).

Classifies user queries into length buckets and assigns max_tokens.
Does not change retrieval or model selection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

# Query type → max completion tokens (kept intentionally tight vs old 1200–1500)
BUDGETS = {
    "fact": 150,
    "definition": 200,
    "summary": 250,
    "comparison": 350,
    "analytical": 500,
    "explanation": 800,
    "timeline": 400,
    "default": 350,
}

_FACT = re.compile(
    r"\b(what is the|who is|when was|when did|how many|how much|which|where is|"
    r"list (the )?(top|all|primary)|name the|yes or no)\b",
    re.I,
)
_DEF = re.compile(r"\b(define|definition|what does .+ mean|meaning of)\b", re.I)
_SUM = re.compile(
    r"\b(summarize|summary|overview|tldr|tl;dr|sum up|brief|key (findings|points)|"
    r"in (one|1|five|5) (paragraph|bullet|bullets))\b",
    re.I,
)
_CMP = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|baseline versus|"
    r"pros and cons)\b",
    re.I,
)
_ANALYTICAL = re.compile(
    r"\b(analyze|analysis|evaluate|assessment|implications|trade-?offs|"
    r"limitations|risks|why did|root cause)\b",
    re.I,
)
_EXPLAIN = re.compile(
    r"\b(explain|elaborate|walk me through|how does|how do|deep dive|"
    r"like i('m| am) a beginner|in detail|detailed)\b",
    re.I,
)
_TIMELINE = re.compile(
    r"\b(timeline|chronolog|sequence of events|milestones|history of)\b",
    re.I,
)


@dataclass(frozen=True)
class ResponsePlan:
    query_type: str
    max_tokens: int
    concise: bool  # shorter prompt structure


def classify_response_length(query: str) -> ResponsePlan:
    q = query or ""
    if _TIMELINE.search(q):
        return ResponsePlan("timeline", BUDGETS["timeline"], concise=False)
    if _SUM.search(q):
        return ResponsePlan("summary", BUDGETS["summary"], concise=True)
    if _CMP.search(q):
        return ResponsePlan("comparison", BUDGETS["comparison"], concise=False)
    if _EXPLAIN.search(q):
        return ResponsePlan("explanation", BUDGETS["explanation"], concise=False)
    if _ANALYTICAL.search(q):
        return ResponsePlan("analytical", BUDGETS["analytical"], concise=False)
    if _DEF.search(q):
        return ResponsePlan("definition", BUDGETS["definition"], concise=True)
    if _FACT.search(q) or len(q.split()) <= 8:
        return ResponsePlan("fact", BUDGETS["fact"], concise=True)
    return ResponsePlan("default", BUDGETS["default"], concise=True)


def plan_for_query(query: str) -> Tuple[str, int, bool]:
    p = classify_response_length(query)
    return p.query_type, p.max_tokens, p.concise
