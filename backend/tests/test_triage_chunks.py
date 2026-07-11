"""Tests for triage element → chunk mapping (no empty-chunk regressions)."""
from __future__ import annotations

from types import SimpleNamespace

from src.agents.triage import _element_content, _elements_to_chunks


class _El:
    def __init__(self, text, cls_name="Text"):
        self.text = text
        self.__class__.__name__ = cls_name


def test_text_elements_are_not_dropped():
    """fast strategy often yields Text, not NarrativeText — must still chunk."""
    from unstructured.documents.elements import Text, NarrativeText, Title

    elements = [
        Title(text="Hello"),
        NarrativeText(text="Narrative body"),
        Text(text="Plain text body"),
    ]
    chunks = _elements_to_chunks(elements, "doc1")
    assert len(chunks) == 3
    assert chunks[0].type == "Title"
    assert chunks[1].type == "Text"
    assert chunks[2].type == "Text"
    assert "Plain text" in chunks[2].content


def test_empty_elements_skipped():
    from unstructured.documents.elements import Text

    chunks = _elements_to_chunks([Text(text="   "), Text(text="ok")], "doc1")
    assert len(chunks) == 1
    assert chunks[0].content == "ok"


def test_unknown_element_uses_text():
    el = SimpleNamespace(text="misc caption")
    # Simulate duck-typed element without isinstance matches
    typ, content = _element_content(el)  # type: ignore[arg-type]
    assert content == "misc caption"
    assert typ == "Other"
