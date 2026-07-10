"""S3-compatible object storage (Cloudflare R2 + AWS S3)."""
from __future__ import annotations

import logging
from typing import Optional

from src.storage.base import StoredObject

log = logging.getLogger("storage.s3")


class S3ObjectStorage:
    """
    Works for:
      - Cloudflare R2 (custom endpoint)
      - AWS S3 (default endpoint)
    """

    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "auto",
        endpoint_url: Optional[str] = None,
        public_base_url: Optional[str] = None,
        backend_label: str = "s3",
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.public_base_url = (public_base_url or "").rstrip("/") or None
        self.backend_name = backend_label
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "auto",
            config=Config(signature_version="s3v4"),
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: Optional[str] = None,
        original_filename: str = "upload",
    ) -> StoredObject:
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        extra["Metadata"] = {"original_filename": original_filename[:200]}
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        file_url = None
        if self.public_base_url:
            file_url = f"{self.public_base_url}/{key}"
        return StoredObject(
            storage_key=key,
            file_url=file_url,
            byte_size=len(data),
            content_type=content_type,
            original_filename=original_filename,
        )

    def download_to_path(self, key: str, dest_path: str) -> str:
        import os

        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        self._client.download_file(self.bucket, key, dest_path)
        return dest_path

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            log.warning(f"S3 delete failed for {key}: {e}")

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def health_check(self) -> bool:
        # Lightweight: list with max 1 key (or head bucket)
        self._client.head_bucket(Bucket=self.bucket)
        return True
