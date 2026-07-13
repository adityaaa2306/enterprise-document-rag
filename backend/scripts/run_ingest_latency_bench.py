#!/usr/bin/env python3
"""Upload a PDF, wait for job complete, print ingestion_latency stage table."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

API = (os.environ.get("API_URL") or "http://127.0.0.1:8000").rstrip("/")
PDF = Path(os.environ.get("BENCH_PDF") or Path(__file__).resolve().parents[2] / "FinalReport.pdf")
EMAIL = os.environ.get("E2E_EMAIL") or f"ingest-bench-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = os.environ.get("E2E_PASSWORD") or "SecurePass123!"
POLL_TIMEOUT = int(os.environ.get("E2E_POLL_TIMEOUT_SEC") or "1800")
POLL_INTERVAL = float(os.environ.get("E2E_POLL_INTERVAL_SEC") or "5")


def main() -> int:
    print(f"API={API}")
    print(f"PDF={PDF} exists={PDF.is_file()}")
    if not PDF.is_file():
        return 2

    s = requests.Session()
    s.post(f"{API}/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "bench"}, timeout=60)
    login = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=60)
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"auth ok {EMAIL}")

    with PDF.open("rb") as f:
        up = s.post(
            f"{API}/summarize?mode=automatic",
            headers=headers,
            files={"file": (PDF.name, f, "application/pdf")},
            timeout=180,
        )
    print(f"upload status={up.status_code} body={up.text[:300]}")
    up.raise_for_status()
    job_id = up.json()["job_id"]
    print(f"job_id={job_id}")

    deadline = time.time() + POLL_TIMEOUT
    last = None
    while time.time() < deadline:
        st = s.get(f"{API}/job-status/{job_id}", headers=headers, timeout=60)
        if st.status_code in (502, 503, 504):
            time.sleep(POLL_INTERVAL)
            continue
        st.raise_for_status()
        body = st.json()
        status = body.get("status")
        msg = body.get("message")
        if (status, msg) != last:
            print(f"  status={status} progress={body.get('progress')} msg={msg}")
            last = (status, msg)
        if status in ("complete", "completed"):
            break
        if status in ("error", "failed"):
            print("JOB FAILED", body)
            return 1
        time.sleep(POLL_INTERVAL)
    else:
        print("TIMEOUT")
        return 1

    res = s.get(f"{API}/job-result/{job_id}", headers=headers, timeout=120)
    res.raise_for_status()
    data = res.json()
    lat = data.get("ingestion_latency") or {}
    out = Path(__file__).resolve().parents[1] / "local_db" / "aux_e2e" / "ingest_latency" / f"{job_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Prefer on-disk file if finalize wrote it
    disk = Path(__file__).resolve().parents[1] / "local_db" / "aux_e2e" / "ingest_latency" / f"{job_id}.json"
    if disk.is_file() and disk.stat().st_size > 10:
        lat = json.loads(disk.read_text(encoding="utf-8"))
        print(f"loaded disk latency {disk}")
    elif lat:
        out.write_text(json.dumps(lat, indent=2), encoding="utf-8")
        print(f"wrote result latency {out}")
    else:
        # try glob
        matches = list((Path(__file__).resolve().parents[1] / "local_db").glob(f"**/ingest_latency/{job_id}.json"))
        if matches:
            lat = json.loads(matches[0].read_text(encoding="utf-8"))
            print(f"loaded {matches[0]}")

    print("\n=== RAW stages_ms ===")
    print(json.dumps(lat.get("stages_ms") or {}, indent=2))
    print("\n=== map_chunk_stats ===")
    print(json.dumps(lat.get("map_chunk_stats") or {}, indent=2))
    print("\n=== meta (routing) ===")
    meta = lat.get("meta") or {}
    for k in ("routing_summary", "total_chunks", "map_max_workers", "feature_classifier", "tier", "selected_model"):
        if k in meta:
            print(f"  {k}: {meta[k]}")

    # Time to first chunk from chunk_calls
    calls = lat.get("chunk_calls") or []
    if calls:
        first = min(calls, key=lambda c: c.get("chunk_index", 999))
        # approximate: map stage start isn't stored; use min call among first wave
        map_calls = [c for c in calls if c.get("phase") == "map"]
        if map_calls:
            # first completed = smallest (queue+call) among early workers isn't exact;
            # report first-finished call_ms and the stage map_summarize_ms
            print("\n=== first map chunk_calls (by completion order approx via call end) ===")
            # sort by queue+call as proxy for finish time from stage start for first wave
            ranked = sorted(map_calls, key=lambda c: float(c.get("queue_ms") or 0) + float(c.get("call_ms") or 0))
            for c in ranked[:3]:
                print(
                    f"  chunk={c.get('chunk_index')} model={c.get('model_id')} "
                    f"queue_ms={c.get('queue_ms')} call_ms={c.get('call_ms')} "
                    f"retries={c.get('retry_count')} attempts={c.get('attempt_count')} ok={c.get('success')}"
                )
            ttf = float(ranked[0].get("queue_ms") or 0) + float(ranked[0].get("call_ms") or 0)
            print(f"\nTIME_TO_FIRST_CHUNK_MS={ttf:.1f}")

    stages = lat.get("stages_ms") or {}
    print(f"FEATURE_EXTRACT_MS={stages.get('feature_extract_ms')}")
    print(f"MAP_SUMMARIZE_MS={stages.get('map_summarize_ms')}")
    print(f"TOTAL_MS={stages.get('total_ms')}")
    print(f"JOB_ID={job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
