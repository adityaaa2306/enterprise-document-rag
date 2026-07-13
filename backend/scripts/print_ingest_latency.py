#!/usr/bin/env python3
"""
Print ingestion latency table for a completed job.

Reads either:
  - local_db/aux*/ingest_latency/<job_id>.json  (written by finalize_metrics)
  - or GET /job-result/<job_id> → result.ingestion_latency

Usage:
  python scripts/print_ingest_latency.py --job-id <uuid>
  python scripts/print_ingest_latency.py --job-id <uuid> --api http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.monitoring.ingestion_latency import format_latency_table


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument("--api", default=os.environ.get("API_URL", ""))
    p.add_argument("--email", default=os.environ.get("E2E_EMAIL", ""))
    p.add_argument("--password", default=os.environ.get("E2E_PASSWORD", ""))
    p.add_argument(
        "--path",
        default="",
        help="Direct path to ingest_latency JSON",
    )
    args = p.parse_args()

    data = None
    if args.path:
        data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    else:
        # Search common aux dirs
        root = Path(__file__).resolve().parents[1]
        candidates = list(root.glob(f"local_db/**/ingest_latency/{args.job_id}.json"))
        if candidates:
            data = json.loads(candidates[0].read_text(encoding="utf-8"))
            print(f"Loaded {candidates[0]}")
        elif args.api:
            import requests

            api = args.api.rstrip("/")
            session = requests.Session()
            if args.email and args.password:
                session.post(
                    f"{api}/auth/register",
                    json={
                        "email": args.email,
                        "password": args.password,
                        "full_name": "latency",
                    },
                    timeout=60,
                )
                login = session.post(
                    f"{api}/auth/login",
                    json={"email": args.email, "password": args.password},
                    timeout=60,
                )
                token = login.json().get("access_token")
                headers = {"Authorization": f"Bearer {token}"}
            else:
                headers = {}
            r = session.get(f"{api}/job-result/{args.job_id}", headers=headers, timeout=120)
            r.raise_for_status()
            body = r.json()
            data = body.get("ingestion_latency") or (body.get("result") or {}).get(
                "ingestion_latency"
            )
        else:
            print("No latency file found and --api not set")
            return 2

    if not data:
        print("ingestion_latency missing on result")
        return 1

    print(format_latency_table(data))
    stats = data.get("map_chunk_stats") or {}
    print(f"\nfailures={stats.get('failures')} peak_pool={data.get('pool_peak_active')}")
    meta = data.get("meta") or {}
    if meta.get("routing_summary"):
        print(f"routing: {meta['routing_summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
