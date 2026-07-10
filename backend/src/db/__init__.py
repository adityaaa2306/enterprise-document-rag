"""
Shared SQLAlchemy database layer.

Single declarative Base + engine/session factory for all relational persistence.
Vector embeddings remain in ChromaDB (not migrated to Postgres/pgvector).
"""
from src.db.base import Base
from src.db.session import (
    get_engine,
    get_session_factory,
    get_session,
    init_engine,
    is_sqlite,
    is_postgres,
    dispose_engine,
)

__all__ = [
    "Base",
    "get_engine",
    "get_session_factory",
    "get_session",
    "init_engine",
    "is_sqlite",
    "is_postgres",
    "dispose_engine",
]
