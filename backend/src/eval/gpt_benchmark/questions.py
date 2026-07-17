"""
Benchmark question suites.

Smoke: 3–5 representative questions for a single small document
(Student Attendance App.pdf) to validate the pipeline before a full suite.
"""
from __future__ import annotations

from typing import Dict, List

# Preferred smoke-test document (repo root).
SMOKE_DOCUMENT_FILENAME = "Student Attendance App.pdf"

SMOKE_QUESTIONS: List[str] = [
    "What is the main purpose of this application?",
    "Who are the primary users or stakeholders?",
    "List the key features described in the document.",
    "How does attendance tracking work according to the document?",
    "What technologies or stack components are mentioned?",
]

FULL_QUESTIONS: List[str] = [
    "What is the main purpose of this application?",
    "Who are the primary users or stakeholders?",
    "List the key features described in the document.",
    "How does attendance tracking work according to the document?",
    "What technologies or stack components are mentioned?",
    "Summarize the system architecture in one paragraph.",
    "What problems does this application aim to solve?",
    "Describe any authentication or role-based access mentioned.",
    "What reports or analytics does the system provide?",
    "List any limitations, risks, or future work mentioned.",
    "How is data stored or persisted?",
    "Explain the student registration or enrollment flow.",
    "What UI screens or modules are described?",
    "How are absences or late arrivals handled?",
    "Provide a concise executive summary of the document.",
]

SUITES: Dict[str, List[str]] = {
    "smoke": SMOKE_QUESTIONS,
    "full": FULL_QUESTIONS,
}


def questions_for_suite(suite: str) -> List[str]:
    key = (suite or "smoke").strip().lower()
    if key not in SUITES:
        raise ValueError(f"Unknown suite '{suite}'. Choose from: {', '.join(SUITES)}")
    return list(SUITES[key])
