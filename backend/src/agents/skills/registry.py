"""Skill registry for Response Agent (Phase 2.D). Skills ≠ agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from src.context.assembler import ContextPack


@dataclass
class SkillSpec:
    name: str
    description: str
    build_messages: Callable[[str, ContextPack], List[Dict[str, str]]]
    max_tokens: int = 1500
    temperature: float = 0.2


_REGISTRY: Dict[str, SkillSpec] = {}


def register(skill: SkillSpec) -> SkillSpec:
    _REGISTRY[skill.name] = skill
    return skill


def get_skill(name: str) -> Optional[SkillSpec]:
    return _REGISTRY.get(name)


def list_skills() -> List[str]:
    return sorted(_REGISTRY.keys())


def ensure_builtins_loaded() -> None:
    """Import skill modules so they self-register."""
    # Local imports avoid circular deps at package import time
    from src.agents.skills import qa as _qa  # noqa: F401
    from src.agents.skills import summarize_excerpt as _sum  # noqa: F401
    from src.agents.skills import timeline as _tl  # noqa: F401
