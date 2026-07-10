"""
Dialect-aware engine and session factory.

Supports:
  - sqlite:///...   (local development)
  - postgresql://... / postgresql+psycopg://...  (production)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings

log = logging.getLogger("db.session")

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def is_sqlite(url: Optional[str] = None) -> bool:
    u = (url or settings.DATABASE_URL or "").lower()
    return u.startswith("sqlite:")


def is_postgres(url: Optional[str] = None) -> bool:
    u = (url or settings.DATABASE_URL or "").lower()
    return u.startswith("postgres")


def _normalize_database_url(url: str) -> str:
    """
    Prefer psycopg (v3) driver when a bare postgresql:// URL is given.
    Leave sqlite and explicit drivers unchanged.
    """
    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        # Heroku / some providers
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    # sqlite:////abs/path or sqlite:///./relative
    raw = url.replace("sqlite:///", "", 1)
    if raw == ":memory:":
        return
    directory = os.path.dirname(os.path.abspath(raw))
    if directory:
        os.makedirs(directory, exist_ok=True)


def init_engine(url: Optional[str] = None, *, echo: bool = False) -> Engine:
    """Create (or recreate) the global engine + session factory."""
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()

    database_url = _normalize_database_url(url or settings.DATABASE_URL)
    connect_args = {}
    engine_kwargs = {"echo": echo, "future": True, "pool_pre_ping": True}

    if is_sqlite(database_url):
        _ensure_sqlite_dir(database_url)
        connect_args["check_same_thread"] = False
        # SQLite: NullPool is fine for local; avoid pool_size kwargs
        engine_kwargs["connect_args"] = connect_args
    else:
        engine_kwargs["pool_size"] = int(getattr(settings, "DB_POOL_SIZE", 5) or 5)
        engine_kwargs["max_overflow"] = int(getattr(settings, "DB_MAX_OVERFLOW", 10) or 10)

    _engine = create_engine(database_url, **engine_kwargs)

    if is_sqlite(database_url):

        @event.listens_for(_engine, "connect")
        def _sqlite_on_connect(dbapi_conn, connection_record):  # noqa: ARG001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine,
        expire_on_commit=False,
    )
    dialect = "sqlite" if is_sqlite(database_url) else "postgresql" if is_postgres(database_url) else "other"
    log.info(f"Database engine initialized ({dialect}) url_scheme={database_url.split(':', 1)[0]}")
    return _engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Session:
    """Open a new Session. Caller must close (or use context manager)."""
    return get_session_factory()()


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
