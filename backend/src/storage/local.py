"""Local filesystem object storage (development / fallback)."""
from __future__ import annotations

import logging
import os
import shutil
from typing import Optional
from urllib.parse import quote

from src.storage.base import StoredObject

log = logging.getLogger("storage.local")


class LocalObjectStorage:
    backend_name = "local"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _full(self, key: str) -> str:
        # Prevent path traversal
        safe = key.replace("\\", "/").lstrip("/")
        full = os.path.abspath(os.path.join(self.root, safe))
        if not full.startswith(self.root):
            raise ValueError("Invalid storage key")
        return full

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: Optional[str] = None,
        original_filename: str = "upload",
    ) -> StoredObject:
        path = self._full(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        # file:// URL for local reference (not served publicly)
        file_url = "file:///" + quote(path.replace("\\", "/"))
        return StoredObject(
            storage_key=key,
            file_url=file_url,
            byte_size=len(data),
            content_type=content_type,
            original_filename=original_filename,
        )

    def download_to_path(self, key: str, dest_path: str) -> str:
        src = self._full(key)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Object not found: {key}")
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".", exist_ok=True)
        shutil.copy2(src, dest_path)
        return dest_path

    def delete(self, key: str) -> None:
        path = self._full(key)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as e:
            log.warning(f"Local delete failed for {key}: {e}")

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._full(key))

    def health_check(self) -> bool:
        probe = os.path.join(self.root, ".health")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
