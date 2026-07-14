"""Production document structure parser (heading validation → sections → pack)."""

from src.structure.pipeline import DocumentStructurePipeline, build_structured_chunks
from src.structure.types import SemanticSection, StructureDiagnostics

__all__ = [
    "DocumentStructurePipeline",
    "build_structured_chunks",
    "SemanticSection",
    "StructureDiagnostics",
]
