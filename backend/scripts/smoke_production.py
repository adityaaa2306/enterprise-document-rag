#!/usr/bin/env python3
"""
Phase 5 — production / staging end-to-end smoke test.

Does not modify AI components. Exercises auth → upload → poll → result → RAG → chat.

Usage:
  set API_URL=https://your-api.onrender.com
  set SMOKE_EMAIL=smoke@example.com
  set SMOKE_PASSWORD=SecurePass123!
  python scripts/smoke_production.py

Optional:
  FRONTEND_URL=https://your-app.vercel.app   # HTTP GET check only
  SKIP_UPLOAD=1                              # auth + health only
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import requests

API_URL = (os.environ.get("API_URL") or os.environ.get("NEXT_PUBLIC_API_URL") or "").rstrip("/")
FRONTEND_URL = (os.environ.get("FRONTEND_URL") or "").rstrip("/")
EMAIL = os.environ.get("SMOKE_EMAIL") or f"smoke-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = os.environ.get("SMOKE_PASSWORD") or "SecurePass123!"
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "").lower() in ("1", "true", "yes")
POLL_TIMEOUT_SEC = int(os.environ.get("SMOKE_POLL_TIMEOUT_SEC") or "600")
POLL_INTERVAL_SEC = float(os.environ.get("SMOKE_POLL_INTERVAL_SEC") or "3")


class SmokeFailure(Exception):
    pass


def _ok(name: str, detail: str = "") -> None:
    print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))


def _fail(name: str, detail: str) -> None:
    raise SmokeFailure(f"{name}: {detail}")


def check_frontend() -> None:
    if not FRONTEND_URL:
        print("  SKIP  frontend (FRONTEND_URL not set)")
        return
    r = requests.get(FRONTEND_URL, timeout=30)
    if r.status_code >= 400:
        _fail("frontend", f"HTTP {r.status_code}")
    _ok("frontend", f"{FRONTEND_URL} → {r.status_code}")


def check_health(session: requests.Session) -> None:
    r = session.get(f"{API_URL}/api/health", timeout=30)
    if r.status_code != 200:
        _fail("api_health", f"HTTP {r.status_code} {r.text[:200]}")
    body = r.json()
    if body.get("status") != "ok":
        _fail("api_health", str(body))
    _ok("api_health", body.get("env", ""))


def check_ready(session: requests.Session) -> Dict[str, Any]:
    r = session.get(f"{API_URL}/api/ready", timeout=60)
    body = r.json() if r.content else {}
    if r.status_code != 200:
        _fail("api_ready", f"HTTP {r.status_code} checks={body.get('checks')}")
    checks = body.get("checks") or {}
    for key in ("database", "object_storage"):
        c = checks.get(key) or {}
        if not c.get("ok"):
            _fail("api_ready", f"{key} not ok: {c}")
    chroma_ok = (checks.get("chroma") or {}).get("ok") or (checks.get("chroma_path") or {}).get("ok")
    if not chroma_ok:
        _fail("api_ready", f"chroma not ok: {checks}")
    _ok("api_ready", f"db={checks.get('database')} storage={checks.get('object_storage')}")
    return checks


def check_worker_health(session: requests.Session) -> None:
    r = session.get(f"{API_URL}/api/worker/health", timeout=30)
    body = r.json() if r.content else {}
    if r.status_code != 200:
        _fail("worker_health", f"HTTP {r.status_code} {body}")
    if int(body.get("alive_count") or 0) < 1:
        _fail("worker_health", f"no live workers: {body}")
    _ok("worker_health", f"alive={body.get('alive_count')}")


def register_login(session: requests.Session) -> Tuple[str, str]:
    # Try register (ok if already exists)
    reg = session.post(
        f"{API_URL}/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Smoke Tester"},
        timeout=60,
    )
    if reg.status_code not in (200, 400, 409):
        # 400 may mean user exists depending on API
        pass

    login = session.post(
        f"{API_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=60,
    )
    if login.status_code != 200:
        _fail("auth_login", f"HTTP {login.status_code} {login.text[:300]}")
    data = login.json()
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    if not access or not refresh:
        _fail("auth_login", "missing tokens")
    _ok("auth_login", EMAIL)

    me = session.get(
        f"{API_URL}/auth/me",
        headers={"Authorization": f"Bearer {access}"},
        timeout=30,
    )
    if me.status_code != 200:
        _fail("auth_me", f"HTTP {me.status_code}")
    _ok("auth_me", me.json().get("email", ""))

    refreshed = session.post(
        f"{API_URL}/auth/refresh",
        json={"refresh_token": refresh},
        timeout=30,
    )
    if refreshed.status_code != 200:
        _fail("auth_refresh", f"HTTP {refreshed.status_code}")
    new_access = refreshed.json().get("access_token")
    if not new_access:
        _fail("auth_refresh", "no access_token")
    _ok("auth_refresh")
    return new_access, refreshed.json().get("refresh_token") or refresh


def upload_and_poll(session: requests.Session, access: str) -> str:
    # Real extractable text (empty PDF shells yield 0 chunks → RAG 404).
    body = (
        "Green Agentic Smoke Document\n\n"
        "This portfolio document describes carbon-aware document intelligence.\n"
        "The system uses NVIDIA NIM models for summarization and retrieval.\n"
        "Key topics: triage, chunking, embeddings, hybrid retrieval, and RAG answers.\n"
        "Smoke verification requires at least one embedded chunk for query matching.\n"
    ).encode("utf-8")
    files = {"file": ("smoke.txt", body, "text/plain")}
    r = session.post(
        f"{API_URL}/summarize?mode=automatic",
        headers={"Authorization": f"Bearer {access}"},
        files=files,
        timeout=120,
    )
    if r.status_code != 200:
        _fail("upload_summarize", f"HTTP {r.status_code} {r.text[:400]}")
    job_id = r.json().get("job_id")
    if not job_id:
        _fail("upload_summarize", "no job_id")
    _ok("upload_summarize", job_id)

    # Job should start as pending (or already processing if worker is fast)
    st = session.get(
        f"{API_URL}/job-status/{job_id}",
        headers={"Authorization": f"Bearer {access}"},
        timeout=120,
    )
    if st.status_code != 200:
        _fail("job_poll", f"status HTTP {st.status_code}")
    status = st.json().get("status")
    _ok("job_poll_initial", status)

    deadline = time.time() + POLL_TIMEOUT_SEC
    last = status
    while time.time() < deadline:
        try:
            st = session.get(
                f"{API_URL}/job-status/{job_id}",
                headers={"Authorization": f"Bearer {access}"},
                timeout=120,
            )
        except requests.RequestException as e:
            # Free-tier cold starts / NIM load can stall the web process briefly
            print(f"  WARN  job_poll transient: {e}")
            time.sleep(max(POLL_INTERVAL_SEC, 5.0))
            continue
        if st.status_code != 200:
            _fail("job_poll", f"HTTP {st.status_code}")
        body = st.json()
        last = body.get("status")
        if last in ("complete", "completed"):
            _ok("job_complete", f"progress={body.get('progress')}")
            return job_id
        if last in ("error", "failed"):
            _fail("job_complete", f"job failed: {body.get('message') or body}")
        time.sleep(POLL_INTERVAL_SEC)

    _fail("job_complete", f"timeout after {POLL_TIMEOUT_SEC}s last_status={last}")


def check_result_rag_chat(session: requests.Session, access: str, job_id: str) -> None:
    headers = {"Authorization": f"Bearer {access}"}
    res = session.get(f"{API_URL}/job-result/{job_id}", headers=headers, timeout=60)
    if res.status_code != 200:
        _fail("job_result", f"HTTP {res.status_code} {res.text[:300]}")
    result = res.json()
    doc_id = result.get("document_id") or job_id
    _ok("job_result", f"document_id={doc_id}")

    rag = session.post(
        f"{API_URL}/rag-query",
        headers=headers,
        json={"document_id": doc_id, "query": "Summarize this document briefly."},
        timeout=180,
    )
    if rag.status_code != 200:
        _fail("rag_query", f"HTTP {rag.status_code} {rag.text[:400]}")
    _ok("rag_query", "chroma retrieval path exercised")

    chat = session.post(
        f"{API_URL}/chat",
        headers=headers,
        json={"document_id": doc_id, "query": "What is this about?", "conversation_id": None},
        timeout=180,
    )
    if chat.status_code != 200:
        _fail("conversations", f"HTTP {chat.status_code} {chat.text[:400]}")
    _ok("conversations", "chat responded")


def main() -> int:
    print("Phase 5 smoke test")
    print(f"  API_URL={API_URL or '(missing)'}")
    print(f"  FRONTEND_URL={FRONTEND_URL or '(optional)'}")
    if not API_URL:
        print("ERROR: Set API_URL to your Render API base URL")
        return 2

    session = requests.Session()
    try:
        check_frontend()
        check_health(session)
        check_ready(session)
        check_worker_health(session)
        access, _refresh = register_login(session)
        if SKIP_UPLOAD:
            print("  SKIP  upload/worker/rag (SKIP_UPLOAD=1)")
        else:
            job_id = upload_and_poll(session, access)
            check_result_rag_chat(session, access, job_id)
        print("\nAll smoke checks passed.")
        return 0
    except SmokeFailure as e:
        print(f"\nFAIL  {e}")
        return 1
    except requests.RequestException as e:
        print(f"\nFAIL  network: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
