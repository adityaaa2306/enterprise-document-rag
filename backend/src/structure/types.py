"""
Production document-structure types.

Used by heading validation → section builder → semantic merge → packing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

HeadingClass = Literal[
    "major_heading",
    "minor_heading",
    "subsection",
    "caption",
    "metadata",
    "footer",
    "header",
    "table_title",
    "figure_title",
    "person_name",
    "date",
    "label",
    "ignore",
    "body",
]

SECTION_OPENING_CLASSES = frozenset(
    {"major_heading", "minor_heading", "subsection"}
)


class LayoutBlock(BaseModel):
    """Atomic layout unit from triage / page extraction."""

    index: int
    text: str
    block_type: str = "Text"  # Title|Text|Table|List|Other (triage hint only)
    page: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class HeadingDecision(BaseModel):
    block_index: int
    text: str
    confidence: float
    classification: HeadingClass
    accepted: bool
    level: int = 0  # 1=major, 2=minor, 3=subsection
    signals: Dict[str, Any] = Field(default_factory=dict)
    reject_reasons: List[str] = Field(default_factory=list)


class SemanticSection(BaseModel):
    """True document section spanning validated heading → next heading."""

    section_id: str
    heading: str
    heading_level: int = 1
    heading_class: HeadingClass = "major_heading"
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    paragraphs: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    figures: List[str] = Field(default_factory=list)
    captions: List[str] = Field(default_factory=list)
    lists: List[str] = Field(default_factory=list)
    equations: List[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    embedding: Optional[List[float]] = None
    importance: float = 0.5
    complexity: float = 0.5
    merge_reason: Optional[str] = None
    source_block_indices: List[int] = Field(default_factory=list)

    def body_text(self) -> str:
        parts: List[str] = []
        if self.heading:
            parts.append(self.heading)
        parts.extend(self.paragraphs)
        parts.extend(self.lists)
        parts.extend(self.tables)
        parts.extend(self.figures)
        parts.extend(self.captions)
        parts.extend(self.equations)
        return "\n\n".join(p for p in parts if (p or "").strip())

    def recount_tokens(self) -> int:
        from src.chunking.service import estimate_tokens

        self.estimated_tokens = estimate_tokens(self.body_text())
        return self.estimated_tokens

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "heading_level": self.heading_level,
            "heading_class": self.heading_class,
            "page_range": (
                f"{self.page_start}-{self.page_end}"
                if self.page_start is not None
                else None
            ),
            "paragraph_count": len(self.paragraphs),
            "tables": len(self.tables),
            "figures": len(self.figures),
            "equations": len(self.equations),
            "lists": len(self.lists),
            "estimated_tokens": self.estimated_tokens,
            "importance": self.importance,
            "complexity": self.complexity,
            "merge_reason": self.merge_reason,
        }


class StructureDiagnostics(BaseModel):
    raw_layout_blocks: int = 0
    heading_candidates: int = 0
    validated_headings: int = 0
    rejected_headings: int = 0
    semantic_sections: int = 0
    merged_sections: int = 0
    packed_chunks: int = 0
    average_chunk_tokens: float = 0.0
    median_chunk_tokens: float = 0.0
    min_chunk_tokens: int = 0
    max_chunk_tokens: int = 0
    validated: List[Dict[str, Any]] = Field(default_factory=list)
    rejected: List[Dict[str, Any]] = Field(default_factory=list)
    merge_events: List[Dict[str, Any]] = Field(default_factory=list)
    split_events: List[Dict[str, Any]] = Field(default_factory=list)
    section_tree: List[Dict[str, Any]] = Field(default_factory=list)
