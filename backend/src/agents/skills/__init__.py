"""Skills package (Phase 2.D)."""
from src.agents.skills.registry import ensure_builtins_loaded, get_skill, list_skills, register, SkillSpec

__all__ = [
    "SkillSpec",
    "register",
    "get_skill",
    "list_skills",
    "ensure_builtins_loaded",
]
