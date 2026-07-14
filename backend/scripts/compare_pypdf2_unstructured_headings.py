#!/usr/bin/env python3
"""
One-off comparison: PyPDF2 page text vs unstructured partition for heading/section signal.

Not a production path — run manually:

  python -m scripts.compare_pypdf2_unstructured_headings path/to/doc.pdf

Reports element counts and heading-like titles so we can see whether the
PyPDF2-first triage path loses structural signal vs unstructured.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import List, Tuple

# Allow `python scripts/...` from repo root or backend/
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_TITLEISH = re.compile(
    r"^(?:[0-9]+(?:\.[0-9]+)*\s+)?[A-Z][A-Za-z0-9 ,/\-]{2,80}$"
)


def _pypdf2_blocks(path: Path) -> List[Tuple[str, str]]:
    from PyPDF2 import PdfReader

    reader = PdfReader(str(path))
    out: List[Tuple[str, str]] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            kind = "Title" if _TITLEISH.match(line) and len(line) < 120 else "Text"
            out.append((kind, line[:500]))
    return out


def _unstructured_blocks(path: Path) -> List[Tuple[str, str]]:
    from unstructured.partition.auto import partition

    elements = partition(filename=str(path), strategy="fast")
    out: List[Tuple[str, str]] = []
    for el in elements:
        cat = getattr(el, "category", None) or type(el).__name__
        text = (getattr(el, "text", None) or str(el) or "").strip()
        if not text:
            continue
        out.append((str(cat), text[:500]))
    return out


def _summarize(label: str, blocks: List[Tuple[str, str]]) -> None:
    kinds = Counter(k for k, _ in blocks)
    titles = [t for k, t in blocks if k.lower() in ("title", "header", "heading")]
    titleish = [t for k, t in blocks if k == "Title" or _TITLEISH.match(t)]
    print(f"\n=== {label} ===")
    print(f"blocks: {len(blocks)}")
    print(f"by_kind: {dict(kinds)}")
    print(f"explicit_title_like: {len(titles)}")
    print(f"heuristic_titleish_lines: {len(titleish)}")
    print("sample titles (up to 15):")
    for t in (titles or titleish)[:15]:
        print(f"  - {t[:100]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path, help="Sample PDF path")
    args = ap.parse_args()
    path = args.pdf
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    print(f"Comparing parsers on {path} ({path.stat().st_size} bytes)")
    try:
        pypdf_blocks = _pypdf2_blocks(path)
        _summarize("PyPDF2 (line heuristic titles)", pypdf_blocks)
    except Exception as e:
        print(f"PyPDF2 failed: {e}", file=sys.stderr)
        pypdf_blocks = []

    try:
        uns_blocks = _unstructured_blocks(path)
        _summarize("unstructured.partition(strategy=fast)", uns_blocks)
    except Exception as e:
        print(f"unstructured failed: {e}", file=sys.stderr)
        uns_blocks = []

    if pypdf_blocks and uns_blocks:
        p_titles = sum(
            1
            for k, t in pypdf_blocks
            if k == "Title" or _TITLEISH.match(t)
        )
        u_titles = sum(
            1
            for k, _ in uns_blocks
            if k.lower() in ("title", "header", "heading")
        )
        print("\n=== Delta ===")
        print(f"PyPDF2 titleish - unstructured titles = {p_titles - u_titles}")
        print(
            "If PyPDF2 << unstructured, triage may lose section structure "
            "on the production PDF-first path."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
