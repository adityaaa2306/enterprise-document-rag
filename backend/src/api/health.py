"""
Liveness and readiness probes.

GET /api/health  — process up + embedded Chroma persist dir usable
GET /api/ready   — relational DB + Chroma + object storage usable
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from src.core.config import settings

log = logging.getLogger("health")

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> Dict[str, Any]:
    """
    Liveness (+ light Chroma check for portfolio deploys).

    Verifies the process is up and embedded Chroma persist directory is
    accessible. Does not perform remote HTTP checks.
    """
    body: Dict[str, Any] = {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.app_env_normalized,
    }
    try:
        from src.memory.chroma import chroma_health_check, is_chroma_ready

        chroma = chroma_health_check()
        body["chroma"] = {
            "ok": bool(chroma.get("ok")),
            "mode": chroma.get("mode"),
            "path": chroma.get("path"),
            "ready": is_chroma_ready() or bool(chroma.get("ok")),
        }
        if not chroma.get("ok"):
            body["status"] = "degraded"
            body["chroma"]["error"] = chroma.get("error")
    except Exception as e:
        body["status"] = "degraded"
        body["chroma"] = {"ok": False, "error": str(e)}
        log.warning(f"Health Chroma check failed: {e}")
    return body


@router.get("/api/ready")
def ready(response: Response) -> Dict[str, Any]:
    """
    Readiness: critical dependencies respond.
    Returns 200 when ready, 503 when not.
    """
    checks: Dict[str, Any] = {}
    ready_ok = True

    # Relational DB
    try:
        from src.db.session import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "dialect": engine.dialect.name}
    except Exception as e:
        ready_ok = False
        checks["database"] = {"ok": False, "error": str(e)}
        log.warning(f"Readiness DB check failed: {e}")

    # Embedded Chroma (PersistentClient — local disk)
    try:
        from src.memory.chroma import chroma_health_check

        chroma = chroma_health_check()
        checks["chroma"] = chroma
        if not chroma.get("ok"):
            ready_ok = False
    except Exception as e:
        ready_ok = False
        checks["chroma"] = {"ok": False, "mode": "persistent", "error": str(e)}
        log.warning(f"Readiness Chroma check failed: {e}")

    # Object storage (local / R2 / S3)
    try:
        from src.storage import get_object_storage

        store = get_object_storage()
        store.health_check()
        checks["object_storage"] = {
            "ok": True,
            "backend": getattr(store, "backend_name", settings.OBJECT_STORAGE_BACKEND),
        }
    except Exception as e:
        ready_ok = False
        checks["object_storage"] = {
            "ok": False,
            "backend": settings.OBJECT_STORAGE_BACKEND,
            "error": str(e),
        }
        log.warning(f"Readiness object storage check failed: {e}")

    body = {
        "status": "ready" if ready_ok else "not_ready",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.app_env_normalized,
        "checks": checks,
    }
    if not ready_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body
