"""
Optional reference-answer datasets for quality evaluation.

Dataset items:
  {
    "question": "...",
    "reference_answer": "...",
    "document_id": "...",   # optional
    "tags": [...]           # optional
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


# Built-in smoke references for Student Attendance App.pdf (editable / overridable).
ATTENDANCE_SMOKE_DATASET: List[Dict[str, Any]] = [
    {
        "question": "What is the main purpose of this application?",
        "reference_answer": (
            "The application helps students track and manage class attendance, "
            "including marking present or absent, monitoring attendance percentages, "
            "and understanding how many classes they can miss while staying within limits."
        ),
        "tags": ["purpose", "overview"],
    },
    {
        "question": "Who are the primary users or stakeholders?",
        "reference_answer": (
            "Primary users include students who track their attendance, and typically "
            "also instructors or administrators who manage class records and oversight."
        ),
        "tags": ["users", "stakeholders"],
    },
    {
        "question": "List the key features described in the document.",
        "reference_answer": (
            "Key features include attendance marking (present/absent), attendance "
            "percentage calculation, projections or remaining allowable absences, "
            "and student-facing views of attendance status."
        ),
        "tags": ["features"],
    },
    {
        "question": "How does attendance tracking work according to the document?",
        "reference_answer": (
            "Attendance is recorded per class session as present or absent, then "
            "aggregated into percentages and related summaries so students can monitor "
            "their standing over time."
        ),
        "tags": ["attendance", "workflow"],
    },
    {
        "question": "What technologies or stack components are mentioned?",
        "reference_answer": (
            "The document mentions the technologies and stack components used to build "
            "the attendance application (frontend, backend, and data storage as described)."
        ),
        "tags": ["stack", "technology"],
    },
]


def _index_by_question(items: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in items:
        q = (item.get("question") or "").strip()
        if q:
            out[q] = item
    return out


def load_dataset_file(path: Path | str) -> List[Dict[str, Any]]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Unsupported dataset format in {p}")
    if not isinstance(items, list):
        raise ValueError("Dataset items must be a list")
    return [dict(x) for x in items if isinstance(x, dict)]


def resolve_dataset(
    *,
    suite: str = "smoke",
    dataset_path: Optional[str | Path] = None,
    dataset_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load optional reference dataset.

    Priority: explicit path → dataset_id file under datasets/ → built-in smoke set.
    """
    if dataset_path:
        return load_dataset_file(dataset_path)

    if dataset_id:
        candidate = DATASETS_DIR / f"{dataset_id}.json"
        if candidate.is_file():
            return load_dataset_file(candidate)
        # Built-in aliases (no file required)
        alias = (dataset_id or "").strip().lower()
        if alias in ("attendance_smoke", "smoke", "builtin_smoke"):
            return list(ATTENDANCE_SMOKE_DATASET)

    key = (suite or "smoke").strip().lower()
    builtin = DATASETS_DIR / f"{key}.json"
    if builtin.is_file():
        return load_dataset_file(builtin)

    if key == "smoke":
        return list(ATTENDANCE_SMOKE_DATASET)
    return []


def reference_for_question(
    question: str,
    dataset: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    return _index_by_question(dataset).get((question or "").strip())
