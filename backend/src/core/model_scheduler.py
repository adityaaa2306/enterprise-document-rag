"""
Model Scheduler facade (documentation boundary).

The Model Scheduler is independent of the Carbon-Aware Region Scheduler.

Responsibilities (unchanged existing modules):
  - Light / Medium / Heavy routing     → intelligent_router / chunk_router
  - Chunk routing & escalation         → orchestrator escalate_* / QVA
  - Compilation & validation           → reduce_compile / quality_validation

This module does not re-implement routing. It exists so the architecture
documents two schedulers clearly:

  RegionScheduler  → where to execute (grid intensity / region)
  ModelScheduler   → how to execute (model tiers / validation)

Do not import Electricity Maps or region selection from model-routing code.
"""
from __future__ import annotations

# Re-export touchpoints for discoverability (no behaviour change).
from src.core import chunk_router, intelligent_router  # noqa: F401

__all__ = ["chunk_router", "intelligent_router"]
