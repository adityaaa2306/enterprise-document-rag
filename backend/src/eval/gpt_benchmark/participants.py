"""
Benchmark participants — OpenAI GPT models + the project's Intelligent Router.

Participant ids are stable artifact keys. Display labels are for UI / reports only.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

# Stable artifact / dashboard key
INTELLIGENT_ROUTER_ID = "intelligent-router"
INTELLIGENT_ROUTER_DISPLAY = "Intelligent Router"

# Aliases accepted on the CLI / --models flag
_SYSTEM_ALIASES = frozenset(
    {
        "intelligent-router",
        "intelligent_router",
        "intelligentrouter",
        "system-router",
        "system_router",
        "router",
        "intelligent router",
    }
)

DEFAULT_GPT_MODELS: Tuple[str, ...] = ("gpt-5-nano", "gpt-5-mini", "gpt-5.5")

# Campaign default: system first, then GPT baselines
DEFAULT_BENCHMARK_PARTICIPANTS: Tuple[str, ...] = (
    INTELLIGENT_ROUTER_ID,
    *DEFAULT_GPT_MODELS,
)


def is_system_participant(participant: str) -> bool:
    key = (participant or "").strip().lower().replace("_", "-")
    key = " ".join(key.split())
    if key in _SYSTEM_ALIASES:
        return True
    return key.replace(" ", "-") in _SYSTEM_ALIASES


def normalize_participant(participant: str) -> str:
    raw = (participant or "").strip()
    if not raw:
        return raw
    if is_system_participant(raw):
        return INTELLIGENT_ROUTER_ID
    return raw


def normalize_participants(participants: Sequence[str] | None) -> List[str]:
    if not participants:
        return list(DEFAULT_BENCHMARK_PARTICIPANTS)
    out: List[str] = []
    seen = set()
    for p in participants:
        n = normalize_participant(p)
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out or list(DEFAULT_BENCHMARK_PARTICIPANTS)


def display_name(participant: str) -> str:
    if is_system_participant(participant) or participant == INTELLIGENT_ROUTER_ID:
        return INTELLIGENT_ROUTER_DISPLAY
    return participant


def participant_kind(participant: str) -> str:
    if is_system_participant(participant) or participant == INTELLIGENT_ROUTER_ID:
        return "system_router"
    return "openai"


def describe_participants(participants: Iterable[str]) -> List[dict]:
    rows = []
    for p in participants:
        n = normalize_participant(p)
        rows.append(
            {
                "id": n,
                "display_name": display_name(n),
                "kind": participant_kind(n),
            }
        )
    return rows
