#!/usr/bin/env python3
"""
End-to-end validation using FinalReport.pdf.

Usage (local):
  set API_URL=http://localhost:8000
  set FINAL_REPORT_PDF=../FinalReport.pdf
  python scripts/e2e_final_report.py

Usage (production):
  set API_URL=https://enterprise-document-rag.onrender.com
  set FINAL_REPORT_PDF=../FinalReport.pdf
  python scripts/e2e_final_report.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import requests

API_URL = (os.environ.get("API_URL") or "http://localhost:8000").rstrip("/")
PDF_PATH = Path(
    os.environ.get("FINAL_REPORT_PDF")
    or Path(__file__).resolve().parents[2] / "FinalReport.pdf"
)
EMAIL = os.environ.get("E2E_EMAIL") or f"e2e-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = os.environ.get("E2E_PASSWORD") or "SecurePass123!"
POLL_TIMEOUT = int(os.environ.get("E2E_POLL_TIMEOUT_SEC") or "1200")
POLL_INTERVAL = float(os.environ.get("E2E_POLL_INTERVAL_SEC") or "5")


class Fail(Exception):
    pass


def ok(name: str, detail: str = "") -> None:
    print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))


def step(name: str) -> None:
    print(f"\n==> {name}")


def get_json(session: requests.Session, path: str, **kw):
    r = session.get(f"{API_URL}{path}", timeout=kw.pop("timeout", 120), **kw)
    return r


def main() -> int:
    print("FinalReport.pdf E2E")
    print(f"  API_URL={API_URL}")
    print(f"  PDF={PDF_PATH}")
    if not PDF_PATH.is_file():
        print(f"ERROR: PDF not found at {PDF_PATH}")
        return 2

    session = requests.Session()
    try:
        step("Health / ready / worker")
        for path, label in (
            ("/api/health", "health"),
            ("/api/ready", "ready"),
            ("/api/worker/health", "worker_health"),
        ):
            for attempt in range(20):
                r = get_json(session, path)
                if r.status_code in (502, 503, 504):
                    time.sleep(3)
                    continue
                if path == "/api/worker/health" and r.status_code == 503:
                    time.sleep(2)
                    continue
                if r.status_code != 200:
                    raise Fail(f"{label}: HTTP {r.status_code} {r.text[:200]}")
                break
            else:
                raise Fail(f"{label}: never became ready")
            ok(label)

        step("Register / login")
        session.post(
            f"{API_URL}/auth/register",
            json={"email": EMAIL, "password": PASSWORD, "full_name": "E2E Tester"},
            timeout=60,
        )
        login = session.post(
            f"{API_URL}/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=60,
        )
        if login.status_code != 200:
            raise Fail(f"login HTTP {login.status_code} {login.text[:300]}")
        access = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}
        ok("auth", EMAIL)

        step("Upload FinalReport.pdf")
        with PDF_PATH.open("rb") as f:
            up = session.post(
                f"{API_URL}/summarize?mode=automatic",
                headers=headers,
                files={"file": ("FinalReport.pdf", f, "application/pdf")},
                timeout=180,
            )
        if up.status_code != 200:
            raise Fail(f"upload HTTP {up.status_code} {up.text[:400]}")
        job_id = up.json()["job_id"]
        ok("upload", job_id)

        step("Poll job until complete")
        deadline = time.time() + POLL_TIMEOUT
        last = "pending"
        while time.time() < deadline:
            try:
                st = session.get(
                    f"{API_URL}/job-status/{job_id}",
                    headers=headers,
                    timeout=120,
                )
            except requests.RequestException as e:
                print(f"  WARN  poll: {e}")
                time.sleep(POLL_INTERVAL)
                continue
            if st.status_code in (502, 503, 504):
                print(f"  WARN  poll HTTP {st.status_code}")
                time.sleep(POLL_INTERVAL)
                continue
            if st.status_code != 200:
                raise Fail(f"status HTTP {st.status_code}")
            body = st.json()
            last = body.get("status")
            prog = body.get("progress")
            if last != getattr(main, "_last", None):
                print(f"  ... status={last} progress={prog}")
                main._last = last  # type: ignore[attr-defined]
            if last in ("complete", "completed"):
                ok("job_complete", f"progress={prog}")
                break
            if last in ("error", "failed"):
                raise Fail(f"job failed: {body.get('message') or body}")
            time.sleep(POLL_INTERVAL)
        else:
            raise Fail(f"timeout last_status={last}")

        step("Job result / summary")
        res = session.get(
            f"{API_URL}/job-result/{job_id}",
            headers=headers,
            timeout=120,
        )
        if res.status_code != 200:
            raise Fail(f"result HTTP {res.status_code} {res.text[:300]}")
        result = res.json()
        summary = (
            result.get("summary")
            or result.get("final_summary")
            or (result.get("result") or {}).get("summary")
            or ""
        )
        if not summary and isinstance(result.get("result"), dict):
            summary = result["result"].get("final_summary") or result["result"].get("summary") or ""
        doc_id = result.get("document_id") or job_id
        ok("job_result", f"doc={doc_id} summary_len={len(str(summary))}")
        if not summary:
            print(f"  WARN  no summary field in result keys={list(result.keys())[:20]}")

        step("RAG query")
        rag = session.post(
            f"{API_URL}/rag-query",
            headers=headers,
            json={
                "document_id": doc_id,
                "query": "What are the main findings or conclusions in this report?",
            },
            timeout=300,
        )
        if rag.status_code != 200:
            raise Fail(f"rag HTTP {rag.status_code} {rag.text[:400]}")
        rag_body = rag.json()
        answer = rag_body.get("answer") or rag_body.get("response") or ""
        ok("rag_query", f"answer_len={len(str(answer))}")
        if len(str(answer)) < 20:
            raise Fail(f"rag answer too short: {answer!r}")

        step("Follow-up chat")
        chat = session.post(
            f"{API_URL}/chat",
            headers=headers,
            json={
                "document_id": doc_id,
                "query": "Summarize the methodology in one short paragraph.",
                "conversation_id": None,
            },
            timeout=300,
        )
        if chat.status_code != 200:
            raise Fail(f"chat HTTP {chat.status_code} {chat.text[:400]}")
        chat_body = chat.json()
        ok("chat", f"keys={list(chat_body.keys())[:8]}")

        print("\nAll FinalReport.pdf E2E checks passed.")
        return 0
    except Fail as e:
        print(f"\nFAIL  {e}")
        return 1
    except requests.RequestException as e:
        print(f"\nFAIL  network: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
