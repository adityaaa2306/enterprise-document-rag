"""
Adaptive chunk types (Phase 2.A).

Duck-compatible with triage.Chunk via ``content`` / ``type`` for CRE + summarizers.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


ChunkType = Literal["Title", "Text", "Table", "List", "Other"]
ChunkKind = Literal["text", "table", "list", "title", "merged"]


class ParentNode(BaseModel):
    """Section parent in the document hierarchy."""

    id: str
    document_id: str
    title: str
    section_path: str
    child_chunk_indices: List[int] = Field(default_factory=list)


class AdaptiveChunk(BaseModel):
    """
    Hierarchy-aware retrieval unit.

    ``content`` is the field consumed by feature extraction and summarizers.
    """

    id: str
    document_id: str
    chunk_index: int
    type: ChunkType = "Text"
    content: str
    parent_id: Optional[str] = None
    section_path: Optional[str] = None
    chunk_kind: ChunkKind = "text"
    token_estimate: int = 0

    def estimate_tokens(self) -> int:
        # Approx: ~4 chars/token for English-ish text
        n = max(1, len(self.content) // 4)
        self.token_estimate = n
        return n
