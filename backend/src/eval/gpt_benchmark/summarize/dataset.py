"""
Optional reference summaries for summarization quality evaluation.

Item schema:
  {
    "document_id": "...",          # optional exact match
    "filename": "...",             # optional basename match
    "reference_summary": "...",    # preferred
    "reference_answer": "...",     # alias accepted by quality layer
    "tags": [...]
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"

# Built-in placeholder — campaigns should supply a real reference via --dataset.
ATTENDANCE_SUMMARIZATION_DATASET: List[Dict[str, Any]] = [
    {
        "filename": "Student Attendance App.pdf",
        "reference_summary": (
            "The Student Attendance App helps students track class attendance, "
            "mark present or absent status, monitor attendance percentages, and "
            "understand remaining allowable absences. Primary users are students, "
            "with instructors or administrators typically managing records. Key "
            "features include attendance marking, percentage calculation, and "
            "student-facing status views."
        ),
        "tags": ["attendance", "smoke"],
    },
]


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


def resolve_summarization_dataset(
    *,
    suite: str = "summarization-smoke",
    dataset_path: Optional[str | Path] = None,
    dataset_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if dataset_path:
        return load_dataset_file(dataset_path)

    if dataset_id:
        candidate = DATASETS_DIR / f"{dataset_id}.json"
        if candidate.is_file():
            return load_dataset_file(candidate)
        alias = (dataset_id or "").strip().lower()
        if alias in ("attendance_smoke", "attendance", "builtin_smoke", "smoke"):
            return list(ATTENDANCE_SUMMARIZATION_DATASET)

    # Prefer suite-named file, else built-in for smoke
    key = (suite or "").strip().lower().replace("_", "-")
    builtin = DATASETS_DIR / f"{key}.json"
    if builtin.is_file():
        return load_dataset_file(builtin)
    if key in ("summarization-smoke", "summarize-smoke", "smoke"):
        return list(ATTENDANCE_SUMMARIZATION_DATASET)
    return []


def reference_for_document(
    *,
    document_id: str,
    filename: Optional[str],
    dataset: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not dataset:
        return None
    doc = (document_id or "").strip()
    name = (filename or "").replace("\\", "/").split("/")[-1].strip().lower()
    for item in dataset:
        item_doc = (item.get("document_id") or "").strip()
        if item_doc and doc and item_doc == doc:
            return dict(item)
    for item in dataset:
        item_name = (
            (item.get("filename") or "").replace("\\", "/").split("/")[-1].strip().lower()
        )
        if name and item_name and item_name == name:
            return dict(item)
    # Single-item datasets apply to the campaign document
    if len(dataset) == 1:
        return dict(dataset[0])
    return None


def extract_reference_summary(item: Optional[Dict[str, Any]]) -> Optional[str]:
    if not item:
        return None
    for key in ("reference_summary", "reference_answer", "reference"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None
