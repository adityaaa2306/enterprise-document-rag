"""
Environment-tier helpers for Settings.

APP_ENV selects development | testing | production behavior.
Import continues via ``from src.core.config import settings`` for compatibility.
"""
from __future__ import annotations

from typing import Literal

AppEnv = Literal["development", "testing", "production"]

VALID_ENVS = frozenset({"development", "testing", "production"})


def normalize_app_env(raw: str | None) -> AppEnv:
    value = (raw or "development").strip().lower()
    if value in ("dev", "local"):
        return "development"
    if value in ("test", "ci"):
        return "testing"
    if value in ("prod", "production"):
        return "production"
    if value in VALID_ENVS:
        return value  # type: ignore[return-value]
    return "development"


def is_production(env: str) -> bool:
    return normalize_app_env(env) == "production"
