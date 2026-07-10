"""
Dialect-aware column types.

JSONB on PostgreSQL; portable JSON on SQLite (and other dialects).
"""
from __future__ import annotations

from sqlalchemy import JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class JSONType(TypeDecorator):
    """
    JSON that uses JSONB on PostgreSQL and SQLAlchemy JSON elsewhere.

    Values are always Python dict/list on the application side.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class FlexibleJSON(TypeDecorator):
    """
    Accept dict/list or legacy JSON strings (from Text columns).

    On bind: pass through dict/list; serialize str as-is if already JSON text
    is not needed — we store native JSON. On result: parse str if needed.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            import json

            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            import json

            try:
                return json.loads(value)
            except Exception:
                return value
        return value
