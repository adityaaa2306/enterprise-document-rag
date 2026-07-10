"""
Object storage for uploaded documents (Phase 2).

PDFs/files live in object storage (R2/S3) or local disk fallback.
Postgres stores metadata + URLs only — never file bytes.
"""
from src.storage.factory import get_object_storage

__all__ = ["get_object_storage"]
