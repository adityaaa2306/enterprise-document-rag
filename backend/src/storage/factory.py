"""Factory for object storage backends."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from src.core.config import settings

log = logging.getLogger("storage.factory")


@lru_cache(maxsize=1)
def get_object_storage() -> Any:
    """
    Return a singleton storage backend.

    OBJECT_STORAGE_BACKEND:
      - local (default) — disk under OBJECT_STORAGE_LOCAL_ROOT
      - r2 — Cloudflare R2
      - s3 — AWS S3
    """
    backend = (getattr(settings, "OBJECT_STORAGE_BACKEND", "local") or "local").strip().lower()

    if backend == "local":
        from src.storage.local import LocalObjectStorage

        root = getattr(settings, "OBJECT_STORAGE_LOCAL_ROOT", "./local_db/object_store")
        log.info(f"Object storage: local root={root}")
        return LocalObjectStorage(root)

    if backend in ("r2", "s3"):
        from src.storage.s3 import S3ObjectStorage

        if backend == "r2":
            account = (settings.R2_ACCOUNT_ID or "").strip()
            access = (settings.R2_ACCESS_KEY_ID or "").strip()
            secret = (settings.R2_SECRET_ACCESS_KEY or "").strip()
            bucket = (settings.R2_BUCKET or "").strip()
            if not all([account, access, secret, bucket]):
                raise RuntimeError(
                    "R2 storage requires R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                    "R2_SECRET_ACCESS_KEY, R2_BUCKET"
                )
            endpoint = settings.R2_ENDPOINT_URL or f"https://{account}.r2.cloudflarestorage.com"
            return S3ObjectStorage(
                bucket=bucket,
                access_key=access,
                secret_key=secret,
                region=settings.R2_REGION or "auto",
                endpoint_url=endpoint,
                public_base_url=settings.R2_PUBLIC_BASE_URL or None,
                backend_label="r2",
            )

        # AWS S3
        access = (settings.AWS_ACCESS_KEY_ID or "").strip()
        secret = (settings.AWS_SECRET_ACCESS_KEY or "").strip()
        bucket = (settings.AWS_S3_BUCKET or "").strip()
        if not all([access, secret, bucket]):
            raise RuntimeError(
                "S3 storage requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET"
            )
        return S3ObjectStorage(
            bucket=bucket,
            access_key=access,
            secret_key=secret,
            region=settings.AWS_REGION or "us-east-1",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            public_base_url=settings.S3_PUBLIC_BASE_URL or None,
            backend_label="s3",
        )

    raise RuntimeError(f"Unknown OBJECT_STORAGE_BACKEND={backend!r} (use local|r2|s3)")


def reset_object_storage_cache() -> None:
    """Clear singleton (tests)."""
    get_object_storage.cache_clear()
