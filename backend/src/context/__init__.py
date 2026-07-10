"""Context assembly package (Phase 2.C)."""
from src.context.assembler import (
    ContextAssembler,
    ContextPack,
    PackedPassage,
    ProvenanceEntry,
    assemble_context,
    budget_for_tier,
)

__all__ = [
    "ContextAssembler",
    "ContextPack",
    "PackedPassage",
    "ProvenanceEntry",
    "assemble_context",
    "budget_for_tier",
]
