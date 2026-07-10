"""Object storage protocol + shared result types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Optional, Protocol


@dataclass
class StoredObject:
    storage_key: str
    file_url: Optional[str]
    byte_size: int
    content_type: Optional[str]
    original_filename: str


class ObjectStorage(Protocol):
    backend_name: str

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: Optional[str] = None,
        original_filename: str = "upload",
    ) -> StoredObject: ...

    def download_to_path(self, key: str, dest_path: str) -> str: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def health_check(self) -> bool: ...
