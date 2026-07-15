#!/usr/bin/env python3
"""Reproduce medium-doc result consistency failure with write/read timeline."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
PDF = Path(__file__).resolve().parents[2] / "eval_docs" / "scale_50p.pdf"
OUT = Path(__file__).resolve().parents[1] / "eval_out"
REV = OUT / "result_revisions"
POLL = 0.5
TIMEOUT = 2400


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_key(result: dict | None) -> str:
    if not isinstance(result, dict):
        return "empty"
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    bg = result.get("background") if isinstance(result.get("background"), dict) else {}
    rd = cd.get("region_decision") if isinstance(cd.get("region_decision"), dict) else {}
    return "|".join(
        [
            str(bg.get("phase") or ""),
            f"{float(cd.get('baseline_cost_gco2e') or 0):.4f}",
            f"{float(cd.get('actual_cost_gco2e') or cd.get('operational_co2e_g') or 0):.4f}",
            f"{float(cd.get('carbon_saved_grams') or 0):.4f}",
            str(cd.get("grid_zone") or rd.get("selected_region_name") or cd.get("compute_location") or ""),
            str(int(float(cd.get("total_chunks") or 0))),
            "pi1" if result.get("processing_insights") else "pi0",
        ]
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    g = s.post(f"{API}/guest/session", timeout=60)
    g.raise_for_status()
    gid = g.json()["guest_session_id"]
    s.headers["X-Guest-Session-Id"] = gid

    with PDF.open("rb") as f:
        up = s.post(
            f"{API}/summarize?mode=automatic",
            files={"file": (PDF.name, f, "application/pdf")},
            timeout=180,
        )
    up.raise_for_status()
    job_id = up.json()["job_id"]
    print(f"job_id={job_id} guest={gid}", flush=True)

    timeline = []
    last_key = "empty"
    max_baseline = 0.0
    regressions = []
    deadline = time.time() + TIMEOUT
    n = 0
    while time.time() < deadline:
        n += 1
        t0 = time.time()
        st = s.get(f"{API}/job-status/{job_id}", timeout=60)
        status = st.json() if st.ok else {"http": st.status_code}
        row = {
            "kind": "STATUS",
            "poll": n,
            "t": utc(),
            "t_epoch": t0,
            "http": st.status_code,
            "status": status.get("status"),
            "progress": status.get("progress"),
            "message": status.get("message"),
            "summary_ready": status.get("summary_ready"),
            "metrics_ready": status.get("metrics_ready"),
            "background_phase": status.get("background_phase"),
        }
        timeline.append(row)

        should_result = False
        msg = str(status.get("message") or "").lower()
        if status.get("summary_ready") or "summary ready" in msg or "search ready" in msg:
            should_result = True
        if str(status.get("status") or "").lower() in ("complete", "completed", "done"):
            should_result = True

        if should_result:
            rr = s.get(f"{API}/job-result/{job_id}?_ts={int(t0*1000)}", timeout=120)
            result = rr.json() if rr.ok else None
            key = sync_key(result)
            cd = (result or {}).get("carbon_data") if isinstance(result, dict) else {}
            baseline = float((cd or {}).get("baseline_cost_gco2e") or 0)
            if baseline > max_baseline:
                max_baseline = baseline
            regressed = max_baseline > 0 and baseline < max_baseline * 0.5 and baseline <= 0.0001
            if regressed or (last_key != "empty" and key != last_key and baseline < max_baseline and max_baseline > 0 and baseline <= 0):
                regressions.append(
                    {
                        "poll": n,
                        "t": utc(),
                        "prev_key": last_key,
                        "new_key": key,
                        "max_baseline_seen": max_baseline,
                        "baseline_now": baseline,
                    }
                )
            timeline.append(
                {
                    "kind": "RESULT",
                    "poll": n,
                    "t": utc(),
                    "t_epoch": t0,
                    "http": rr.status_code,
                    "bytes": len(rr.content) if rr.ok else 0,
                    "sync_key": key,
                    "baseline": baseline,
                    "optimized": float((cd or {}).get("operational_co2e_g") or (cd or {}).get("actual_cost_gco2e") or 0),
                    "region": ((cd or {}).get("region_decision") or {}).get("selected_region_name")
                    if isinstance((cd or {}).get("region_decision"), dict)
                    else (cd or {}).get("compute_location"),
                    "bg_phase": ((result or {}).get("background") or {}).get("phase")
                    if isinstance((result or {}).get("background"), dict)
                    else None,
                    "regressed_from_max_baseline": regressed,
                }
            )
            last_key = key

            if (
                status.get("metrics_ready")
                and str(status.get("background_phase") or "").lower() == "search_ready"
                and baseline > 0
            ):
                # stable success
                break
            if status.get("metrics_ready") and str(status.get("background_phase") or "").lower() == "search_ready":
                # status says ready but result stub — keep a few more reads then stop
                if n > 0 and any(x.get("regressed_from_max_baseline") for x in timeline if x.get("kind") == "RESULT"):
                    # observe a few more
                    if sum(1 for x in timeline if x.get("kind") == "RESULT" and x.get("regressed_from_max_baseline")) >= 2:
                        break

        err = str(status.get("status") or "").lower()
        if err in ("error", "failed", "failure"):
            break
        time.sleep(POLL)

    # Load revision log for this job
    rev_path = REV / f"{job_id}.jsonl"
    writes = []
    if rev_path.is_file():
        for line in rev_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                writes.append(json.loads(line))
    reads_path = REV / f"{job_id}.reads.jsonl"
    reads = []
    if reads_path.is_file():
        for line in reads_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                reads.append(json.loads(line))

    payload = {
        "generated_at": utc(),
        "job_id": job_id,
        "guest_id": gid,
        "doc": str(PDF),
        "max_baseline_seen": max_baseline,
        "client_regressions": regressions,
        "timeline": timeline,
        "writes": writes,
        "reads": reads,
        "write_violations": [w for w in writes if w.get("monotonicity_violations")],
    }
    out_json = OUT / f"consistency_medium_{job_id}.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_json}", flush=True)
    print(f"writes={len(writes)} reads={len(reads)} regressions={len(regressions)} max_baseline={max_baseline}", flush=True)
    for w in writes:
        if w.get("monotonicity_violations") or w.get("sync_key_changed"):
            print(
                f"  REV{w.get('revision')} {w.get('writer')} key={w.get('sync_key')} "
                f"viol={w.get('monotonicity_violations')}",
                flush=True,
            )
    return 0 if not regressions and not payload["write_violations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
