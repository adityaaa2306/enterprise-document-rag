"""Regression tests for document structure parser (FinalReport.pdf + unit cases)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.structure.heading_validator import score_heading_candidate, validate_headings
from src.structure.pipeline import DocumentStructurePipeline
from src.structure.types import LayoutBlock

PDF = Path(__file__).resolve().parents[2] / "FinalReport.pdf"
if not PDF.exists():
    PDF = Path(__file__).resolve().parents[3] / "FinalReport.pdf"


def _block(i: int, text: str, btype: str = "Text") -> LayoutBlock:
    return LayoutBlock(index=i, text=text, block_type=btype, page=1)


class TestHeadingValidation:
    def test_rejects_person_names(self):
        d = score_heading_candidate(_block(0, "Ananya Shimpi"), triage_marked_title=True)
        assert d.accepted is False
        assert "person_name" in d.reject_reasons or d.classification == "person_name"

    def test_rejects_dates(self):
        d = score_heading_candidate(_block(0, "Date: December 2025"), triage_marked_title=True)
        assert d.accepted is False

    def test_rejects_team_label(self):
        d = score_heading_candidate(_block(0, "Team Members:"), triage_marked_title=True)
        assert d.accepted is False

    def test_accepts_numbered_chapter(self):
        d = score_heading_candidate(
            _block(0, "1. PROBLEM STATEMENT AND SCOPE"), triage_marked_title=False
        )
        assert d.accepted is True
        assert d.classification in ("major_heading", "minor_heading", "subsection")

    def test_accepts_subsection(self):
        d = score_heading_candidate(_block(0, "1.1 Problem Statement"))
        assert d.accepted is True
        assert d.level >= 2

    def test_rejects_list_item_without_lexicon(self):
        d = score_heading_candidate(_block(0, "1. Carbon-Aware Model Routing"))
        # Should not open a section (listish / weak numbered)
        assert d.accepted is False or d.classification == "ignore"

    def test_validate_batch_filters_metadata(self):
        blocks = [
            _block(0, "TECHNICAL PROJECT REPORT", "Title"),
            _block(1, "Date: December 2025", "Title"),
            _block(2, "Ananya Shimpi", "Title"),
            _block(3, "1. INTRODUCTION", "Title"),
            _block(4, "Body paragraph about the system."),
        ]
        _, accepted, rejected = validate_headings(blocks)
        texts = {a.text for a in accepted}
        assert "Ananya Shimpi" not in texts
        assert "Date: December 2025" not in texts
        assert any("INTRODUCTION" in a.text for a in accepted)
        assert len(rejected) >= 2


class TestStructurePipelineFinalReport:
    @pytest.mark.skipif(not PDF.exists(), reason="FinalReport.pdf not found")
    def test_finalreport_natural_chunk_count(self):
        from src.agents import triage
        from src.core.config import settings

        raw = triage.triage_document(str(PDF), "application/pdf", settings.TRIAGE_STRATEGY)
        assert len(raw) >= 1
        # Triage must NOT emit hundreds of Title labels anymore
        titles = sum(1 for c in raw if getattr(c, "type", None) == "Title")
        assert titles < 20

        chunks, parents, meta = DocumentStructurePipeline().run(
            raw, document_id="finalreport-test"
        )
        sd = meta["structure_diagnostics"]

        assert sd["validated_headings"] < 120
        assert sd["rejected_headings"] > 50
        assert sd["packed_chunks"] == len(chunks)
        # Natural packing for ~5k-token extract: far below legacy 206, within pack band
        assert 3 <= len(chunks) <= 25
        assert sd["median_chunk_tokens"] >= 400
        assert sd["average_chunk_tokens"] >= 400
        assert sd["min_chunk_tokens"] >= 200
        assert sd["max_chunk_tokens"] <= 1300

        validated_text = " ".join(v["text"] for v in sd["validated"])
        assert "Ananya Shimpi" not in validated_text
        assert "Date: December 2025" not in validated_text

        # No force-cap: chunk count comes from structure, not CHUNK_MAX_COUNT
        assert meta.get("structure_parser") is True
        assert len(chunks) != 48 or sd["median_chunk_tokens"] >= 400

    @pytest.mark.skipif(not PDF.exists(), reason="FinalReport.pdf not found")
    def test_before_vs_after_improvement(self):
        """Legacy false-Title path produced ~206; structure parser must be << that."""
        from src.agents import triage
        from src.core.config import settings

        raw = triage.triage_document(str(PDF), "application/pdf", settings.TRIAGE_STRATEGY)
        chunks, _, meta = DocumentStructurePipeline().run(raw, document_id="cmp")
        assert len(chunks) < 50
        assert meta["structure_diagnostics"]["rejected_headings"] > meta[
            "structure_diagnostics"
        ]["validated_headings"]


class TestGeneralisationFixtures:
    def test_research_paper_style(self):
        blocks = [
            _block(0, "Abstract"),
            _block(1, "We present a novel approach to retrieval."),
            _block(2, "1. Introduction"),
            _block(3, "Large language models consume significant energy."),
            _block(4, "2. Related Work"),
            _block(5, "Prior systems ignore grid carbon intensity."),
            _block(6, "3. Methodology"),
            _block(7, "Our pipeline validates headings before packing."),
            _block(8, "References"),
            _block(9, "Smith et al. 2024."),
        ]
        chunks, _, meta = DocumentStructurePipeline().run(blocks, document_id="paper")
        sd = meta["structure_diagnostics"]
        assert sd["validated_headings"] >= 3
        assert len(chunks) >= 1
        assert len(chunks) <= 8

    def test_legal_style_clauses(self):
        blocks = [
            _block(0, "Article 1. Definitions"),
            _block(1, "For the purposes of this agreement..."),
            _block(2, "Article 2. Obligations"),
            _block(3, "The party shall maintain records."),
            _block(4, "John Smith"),  # signature name — reject
        ]
        _, accepted, rejected = validate_headings(blocks)
        assert any("Article" in a.text for a in accepted)
        assert any(r.text == "John Smith" for r in rejected)
