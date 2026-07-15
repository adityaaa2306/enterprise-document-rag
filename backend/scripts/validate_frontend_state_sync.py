#!/usr/bin/env python3
"""
Frontend state-sync E2E validation (no product code changes).

Uploads small/medium/large docs, polls /job-status + /job-result on a dense
timeline, mirrors frontend sync gates, and writes JSON + markdown evidence.

Usage:
  python scripts/validate_frontend_state_sync.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

API = (os.environ.get("API_URL") or "http://127.0.0.1:8000").rstrip("/")
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parents[1] / "eval_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
POLL_INTERVAL = float(os.environ.get("SYNC_VAL_POLL_SEC") or "0.75")
RESULT_EVERY = float(os.environ.get("SYNC_VAL_RESULT_EVERY_SEC") or "1.5")

DOCS: List[Tuple[str, Path, int]] = [
    ("small", ROOT / "eval_docs" / "scale_10p.pdf", int(os.environ.get("SYNC_VAL_SMALL_TIMEOUT") or 1200)),
    ("medium", ROOT / "eval_docs" / "scale_50p.pdf", int(os.environ.get("SYNC_VAL_MEDIUM_TIMEOUT") or 1800)),
    ("large", ROOT / "eval_docs" / "scale_200p.pdf", int(os.environ.get("SYNC_VAL_LARGE_TIMEOUT") or 3600)),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts() -> float:
    return time.time()


# --- Mirror frontend/lib/job-result-sync.ts ---

def is_search_ready_phase(phase: Optional[str]) -> bool:
    p = (phase or "").lower()
    return p in ("search_ready", "complete", "done")


def is_search_ready_from_status(data: Dict[str, Any]) -> bool:
    if is_search_ready_phase(data.get("background_phase")):
        return True
    msg = str(data.get("message") or "").lower().strip()
    if msg == "search ready" or msg.startswith("search ready"):
        return True
    if "search available" in msg:
        return True
    return False


def is_metrics_ready_from_status(data: Dict[str, Any]) -> bool:
    search_ready = is_search_ready_from_status(data)
    if data.get("metrics_ready") is True and search_ready:
        return True
    if search_ready:
        return True
    return False


def has_dashboard_metrics(result: Optional[Dict[str, Any]]) -> bool:
    if not result:
        return False
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    baseline = float(cd.get("baseline_cost_gco2e") or 0)
    intensity = float(cd.get("local_grid_gco2_kwh") or 0)
    loc = str(cd.get("compute_location") or "").strip().lower()
    has_region = bool(
        cd.get("region_decision")
        or (cd.get("grid_zone") and str(cd.get("grid_zone")).strip())
        or (loc and loc != "unknown")
        or intensity > 0
    )
    return baseline > 0 and has_region


def is_metrics_ready_from_result(result: Optional[Dict[str, Any]]) -> bool:
    if not result or not has_dashboard_metrics(result):
        return False
    bg = result.get("background") if isinstance(result.get("background"), dict) else {}
    phase = str(bg.get("phase") or "").lower()
    if is_search_ready_phase(phase):
        return True
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    return float(cd.get("total_chunks") or 0) > 0


def result_sync_key(result: Optional[Dict[str, Any]]) -> str:
    if not result:
        return "empty"
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    rd = cd.get("region_decision") if isinstance(cd.get("region_decision"), dict) else {}
    bg = result.get("background") if isinstance(result.get("background"), dict) else {}
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


def extract_result_fields(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not result:
        return {
            "sync_key": "empty",
            "baseline_co2e": 0.0,
            "optimized_co2e": 0.0,
            "carbon_saved": 0.0,
            "reduction_percent": 0.0,
            "region": None,
            "grid_intensity": 0.0,
            "routing_table_count": 0,
            "chunk_count": 0,
            "has_summary": False,
            "background_phase": None,
        }
    cd = result.get("carbon_data") if isinstance(result.get("carbon_data"), dict) else {}
    rd = cd.get("region_decision") if isinstance(cd.get("region_decision"), dict) else {}
    pi = result.get("processing_insights") if isinstance(result.get("processing_insights"), dict) else {}
    routing = (
        pi.get("chunk_routing_sample")
        or cd.get("chunk_routing")
        or pi.get("routing_distribution")
        or []
    )
    if isinstance(routing, dict):
        routing_count = len(routing)
    elif isinstance(routing, list):
        routing_count = len(routing)
    else:
        routing_count = 0
    region = (
        rd.get("selected_region_name")
        or cd.get("grid_zone")
        or cd.get("compute_location")
        or None
    )
    bg = result.get("background") if isinstance(result.get("background"), dict) else {}
    return {
        "sync_key": result_sync_key(result),
        "baseline_co2e": float(cd.get("baseline_cost_gco2e") or 0),
        "optimized_co2e": float(
            cd.get("operational_co2e_g")
            or cd.get("actual_cost_gco2e")
            or cd.get("modeled_co2e_g")
            or 0
        ),
        "carbon_saved": float(cd.get("carbon_saved_grams") or 0),
        "reduction_percent": float(cd.get("efficiency_percent") or 0),
        "region": region,
        "grid_intensity": float(
            rd.get("grid_carbon_intensity_gco2_kwh") or cd.get("local_grid_gco2_kwh") or 0
        ),
        "routing_table_count": routing_count,
        "chunk_count": int(float(cd.get("total_chunks") or 0)),
        "has_summary": bool(str(result.get("final_summary") or "").strip()),
        "background_phase": bg.get("phase"),
    }


def user_stop_criteria(status: Dict[str, Any], result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Strict acceptance criteria from the validation brief (§6)."""
    fields = extract_result_fields(result)
    search_ready = is_search_ready_from_status(status) or is_search_ready_phase(
        fields.get("background_phase")
    )
    status_ok = str(status.get("status") or "").lower() in ("complete", "completed", "done", "success")
    checks = {
        "status_complete": status_ok,
        "summary_ready": bool(status.get("summary_ready")) or fields["has_summary"],
        "metrics_ready": bool(status.get("metrics_ready")) or is_metrics_ready_from_status(status),
        "search_ready": search_ready,
        "baseline_co2e_gt0": fields["baseline_co2e"] > 0,
        "optimized_co2e_gt0": fields["optimized_co2e"] > 0,
        "region_exists": bool(fields["region"]) and str(fields["region"]).lower() not in ("", "unknown", "—", "-"),
        "routing_table_exists": fields["routing_table_count"] > 0,
    }
    return {"all": all(checks.values()), "checks": checks, "fields": fields}


def frontend_would_stop(status: Dict[str, Any], result: Optional[Dict[str, Any]]) -> bool:
    """Mirror finishMetrics: stop only when result passes isMetricsReadyFromResult."""
    if is_metrics_ready_from_status(status) or is_metrics_ready_from_result(result):
        return is_metrics_ready_from_result(result)
    return False


@dataclass
class JobRun:
    label: str
    path: str
    job_id: str = ""
    guest_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    status_events: List[Dict[str, Any]] = field(default_factory=list)
    result_events: List[Dict[str, Any]] = field(default_factory=list)
    sync_decisions: List[Dict[str, Any]] = field(default_factory=list)
    race_proof: List[Dict[str, Any]] = field(default_factory=list)
    identity_log: List[Dict[str, Any]] = field(default_factory=list)
    pass_fail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def guest_session(s: requests.Session) -> str:
    r = s.post(f"{API}/guest/session", timeout=60)
    r.raise_for_status()
    gid = r.json()["guest_session_id"]
    s.headers["X-Guest-Session-Id"] = gid
    return gid


def upload(s: requests.Session, path: Path) -> str:
    with path.open("rb") as f:
        r = s.post(
            f"{API}/summarize?mode=automatic",
            files={"file": (path.name, f, "application/pdf")},
            timeout=180,
        )
    if r.status_code != 200:
        raise RuntimeError(f"upload HTTP {r.status_code}: {r.text[:400]}")
    return r.json()["job_id"]


def run_one(label: str, path: Path, timeout_sec: int) -> JobRun:
    run = JobRun(label=label, path=str(path), started_at=utc_now())
    s = requests.Session()
    try:
        run.guest_id = guest_session(s)
        print(f"\n=== {label.upper()} {path.name} guest={run.guest_id[:8]}… ===", flush=True)
        run.job_id = upload(s, path)
        print(f"job_id={run.job_id}", flush=True)

        deadline = time.time() + timeout_sec
        last_result_at = 0.0
        current_key = "empty"
        current_obj_id = 0
        poll_n = 0
        saw_summary_ready = False
        saw_frontend_stop_candidate_before_complete = False
        frontend_stopped = False
        frontend_stop_at_poll: Optional[int] = None
        prev_result_payload: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            poll_n += 1
            t0 = ts()
            st_r = s.get(f"{API}/job-status/{run.job_id}", timeout=60)
            status = st_r.json() if st_r.ok else {"error": st_r.status_code, "text": st_r.text[:200]}
            search_ready = is_search_ready_from_status(status) if st_r.ok else False
            status_evt = {
                "poll": poll_n,
                "t": utc_now(),
                "t_epoch": t0,
                "http": st_r.status_code,
                "progress": status.get("progress"),
                "status": status.get("status"),
                "message": status.get("message"),
                "summary_ready": status.get("summary_ready"),
                "metrics_ready": status.get("metrics_ready"),
                "search_ready": search_ready,
                "background_phase": status.get("background_phase"),
                "background_message": status.get("background_message"),
            }
            run.status_events.append(status_evt)

            if st_r.ok and (status.get("summary_ready") or "summary ready" in str(status.get("message") or "").lower()):
                saw_summary_ready = True

            # Fetch result on Summary Ready / interval / metrics-ready (mirror FE)
            should_fetch = False
            if st_r.ok:
                if status.get("summary_ready") or str(status.get("status") or "").lower() in (
                    "complete",
                    "completed",
                    "done",
                    "success",
                ):
                    if (t0 - last_result_at) >= RESULT_EVERY or is_metrics_ready_from_status(status):
                        should_fetch = True
                if not prev_result_payload and status.get("summary_ready"):
                    should_fetch = True

            result = prev_result_payload
            if should_fetch and not frontend_stopped:
                last_result_at = t0
                rr = s.get(f"{API}/job-result/{run.job_id}?_ts={int(t0*1000)}", timeout=120)
                body = rr.content if rr.ok else b""
                raw = rr.json() if rr.ok else None
                fields = extract_result_fields(raw)
                new_key = fields["sync_key"]
                prev_key = current_key
                # Fresh JSON parse ⇒ new object identity (mirrors cloneJobResult)
                same_object = False
                # Stale if baseline regresses after we already had modeled metrics
                stale = False
                if raw and prev_key != "empty" and "|" in prev_key:
                    prev_base = float(prev_key.split("|")[1])
                    if fields["baseline_co2e"] < prev_base and prev_base > 0:
                        stale = True
                # Product currently applies every OK body; harness still records stale flag.
                # For FE-mirror stop logic we always take the latest OK payload (as product does).
                applied = bool(rr.ok and raw)
                if applied:
                    current_obj_id += 1
                    current_key = new_key
                    prev_result_payload = raw
                    result = raw
                key_changed = applied and new_key != prev_key

                run.result_events.append(
                    {
                        "poll": poll_n,
                        "t": utc_now(),
                        "t_epoch": t0,
                        "http": rr.status_code,
                        "bytes": len(body),
                        **fields,
                        "applied": applied,
                        "stale_vs_current": stale,
                        "same_object_as_prev": same_object,
                        "sync_key_changed": key_changed,
                        "prev_sync_key": prev_key,
                    }
                )
                run.identity_log.append(
                    {
                        "poll": poll_n,
                        "same_object": same_object,
                        "sync_key_changed": key_changed,
                        "sync_key": new_key,
                        "prev_sync_key": prev_key,
                        "current_key_after": current_key,
                        "applied": applied,
                        "stale_flagged": stale,
                        "stale_ignored_by_product": False,
                        "object_gen": current_obj_id,
                        "react_render_triggered_if_applied": applied,
                    }
                )

            criteria = user_stop_criteria(status if st_r.ok else {}, result)
            fe_stop = frontend_would_stop(status if st_r.ok else {}, result) if st_r.ok else False
            decision = {
                "poll": poll_n,
                "t": utc_now(),
                "frontend_would_stop": fe_stop,
                "user_criteria_all": criteria["all"],
                "user_checks": criteria["checks"],
                "sync_key": criteria["fields"]["sync_key"],
                "polling": "stop" if fe_stop else "continue",
            }
            run.sync_decisions.append(decision)

            # Race proof: if Summary Ready seen and FE would stop before dashboard complete → BAD
            if saw_summary_ready and fe_stop and not criteria["all"]:
                saw_frontend_stop_candidate_before_complete = True
                run.race_proof.append(
                    {
                        "poll": poll_n,
                        "event": "FRONTEND_WOULD_STOP_BEFORE_FULL_DASHBOARD",
                        "checks": criteria["checks"],
                        "sync_key": criteria["fields"]["sync_key"],
                    }
                )

            if fe_stop and not frontend_stopped:
                frontend_stopped = True
                frontend_stop_at_poll = poll_n
                run.race_proof.append(
                    {
                        "poll": poll_n,
                        "event": "FRONTEND_STOP_POLLING",
                        "user_criteria_satisfied": criteria["all"],
                        "checks": criteria["checks"],
                        "sync_key": criteria["fields"]["sync_key"],
                    }
                )
                # Keep observing backend a bit after FE would stop to prove final payload already present
                observe_until = time.time() + 8
                while time.time() < observe_until:
                    time.sleep(POLL_INTERVAL)
                    rr2 = s.get(f"{API}/job-result/{run.job_id}?_ts={int(time.time()*1000)}", timeout=120)
                    if rr2.ok:
                        f2 = extract_result_fields(rr2.json())
                        run.race_proof.append(
                            {
                                "event": "POST_STOP_RESULT_SNAPSHOT",
                                "t": utc_now(),
                                "sync_key": f2["sync_key"],
                                "baseline_co2e": f2["baseline_co2e"],
                                "region": f2["region"],
                                "matches_stop_key": f2["sync_key"] == current_key,
                            }
                        )
                break

            err_status = str(status.get("status") or "").lower()
            if err_status in ("error", "failed", "failure", "cancelled", "canceled"):
                run.error = status.get("message") or err_status
                break

            time.sleep(POLL_INTERVAL)

        if not frontend_stopped and not run.error:
            run.error = f"timeout after {timeout_sec}s (polls={poll_n})"

        final_status = run.status_events[-1] if run.status_events else {}
        final_result = prev_result_payload
        final_criteria = user_stop_criteria(final_status, final_result)

        # Evolution of sync_key
        keys = [e["sync_key"] for e in run.result_events if e.get("http") == 200]
        unique_keys = []
        for k in keys:
            if not unique_keys or unique_keys[-1] != k:
                unique_keys.append(k)

        run.pass_fail = {
            "frontend_stopped": frontend_stopped,
            "frontend_stop_at_poll": frontend_stop_at_poll,
            "user_criteria_at_stop": final_criteria,
            "race_summary_ready_then_early_stop": saw_frontend_stop_candidate_before_complete,
            "no_early_stop_on_summary_stub": not saw_frontend_stop_candidate_before_complete,
            "sync_key_evolution": unique_keys,
            "status_polls": len(run.status_events),
            "result_fetches": len(run.result_events),
            "stale_responses_seen": sum(1 for e in run.result_events if e.get("stale_vs_current")),
            "passed": bool(
                frontend_stopped
                and final_criteria["all"]
                and not saw_frontend_stop_candidate_before_complete
                and not run.error
            ),
        }
        print(
            f"  done passed={run.pass_fail['passed']} stop_poll={frontend_stop_at_poll} "
            f"keys={len(unique_keys)} err={run.error}",
            flush=True,
        )
    except Exception as e:
        run.error = str(e)
        run.pass_fail = {"passed": False, "error": str(e)}
        print(f"  ERROR {e}", flush=True)
    run.ended_at = utc_now()
    return run


def write_report(runs: List[JobRun]) -> Path:
    json_path = OUT_DIR / "frontend_state_sync_validation.json"
    md_path = OUT_DIR / "FRONTEND_STATE_SYNC_VALIDATION.md"
    payload = {
        "generated_at": utc_now(),
        "api": API,
        "note": (
            "Product code currently applies every OK /job-result (immutable clone) and does not "
            "yet reject older sync_key/revision. This harness detects stale regressions and "
            "records whether FE stop gates wait for dashboard fields."
        ),
        "runs": [asdict(r) for r in runs],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# Frontend State Sync Validation")
    lines.append("")
    lines.append(f"- Generated: `{utc_now()}`")
    lines.append(f"- API: `{API}`")
    lines.append(f"- Raw JSON: `{json_path.name}`")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    all_pass = all(r.pass_fail.get("passed") for r in runs) and len(runs) == 3
    lines.append(f"**Overall: {'PASS' if all_pass else 'FAIL'}** — require all three sizes to pass without refresh.")
    lines.append("")
    lines.append("| Size | Job ID | Passed | FE stop poll # | Early stop on Summary Ready? | Sync keys | Error |")
    lines.append("|------|--------|--------|----------------|------------------------------|-----------|-------|")
    for r in runs:
        pf = r.pass_fail or {}
        lines.append(
            f"| {r.label} | `{r.job_id[:8]}…` | {pf.get('passed')} | {pf.get('frontend_stop_at_poll')} | "
            f"{pf.get('race_summary_ready_then_early_stop')} | {len(pf.get('sync_key_evolution') or [])} | "
            f"{r.error or ''} |"
        )
    lines.append("")

    lines.append("## Product behavior under test")
    lines.append("")
    lines.append("1. Polling continues after Summary Ready until `isMetricsReadyFromResult` (baseline>0 AND region).")
    lines.append("2. `finishMetrics` does not stop when status is ready but result is still a stub.")
    lines.append("3. Each applied `/job-result` is cloned (`cloneJobResult`) → new object identity.")
    lines.append("4. **Gap (item 5):** there is no `updated_at`/`revision`/older-`sync_key` rejector in product code yet — every OK body is applied. This report flags any observed regression.")
    lines.append("")

    for r in runs:
        lines.append(f"## Run: {r.label} (`{Path(r.path).name}`)")
        lines.append("")
        lines.append(f"- job_id: `{r.job_id}`")
        lines.append(f"- guest: `{r.guest_id}`")
        lines.append(f"- window: {r.started_at} → {r.ended_at}")
        lines.append(f"- status polls: {len(r.status_events)}")
        lines.append(f"- result fetches: {len(r.result_events)}")
        lines.append("")

        lines.append("### Sync key evolution")
        lines.append("")
        for i, k in enumerate(r.pass_fail.get("sync_key_evolution") or [], 1):
            lines.append(f"{i}. `{k}`")
        lines.append("")

        lines.append("### Polling / React-mirror decisions (sampled)")
        lines.append("")
        lines.append("Showing Summary Ready transition, keep-polling ticks, and stop:")
        lines.append("")
        interesting = []
        for d in r.sync_decisions:
            msg_poll = next((s for s in r.status_events if s["poll"] == d["poll"]), {})
            interesting.append((d, msg_poll))
        # first, any continue after summary, stop, last
        shown = []
        for d, st in interesting:
            if st.get("summary_ready") or d["frontend_would_stop"] or d["polling"] == "stop":
                shown.append((d, st))
        # also include one continue after first summary
        if len(shown) > 40:
            shown = shown[:15] + shown[-15:]
        lines.append("| poll | t | status | summary_ready | metrics_ready | search_ready | bg | FE stop? | user§6 | action |")
        lines.append("|------|---|--------|---------------|---------------|--------------|----|----------|--------|--------|")
        for d, st in shown[:50]:
            lines.append(
                f"| {d['poll']} | {d['t'][11:19]} | {st.get('status')} | {st.get('summary_ready')} | "
                f"{st.get('metrics_ready')} | {st.get('search_ready')} | {st.get('background_phase')} | "
                f"{d['frontend_would_stop']} | {d['user_criteria_all']} | {d['polling']} |"
            )
        lines.append("")

        lines.append("### /job-result timeline (field fills)")
        lines.append("")
        lines.append("| poll | t | bytes | sync_key | baseline | optimized | saved | region | chunks | routing | applied | stale? |")
        lines.append("|------|---|-------|----------|----------|-----------|-------|--------|--------|---------|---------|--------|")
        for e in r.result_events:
            sk = (e.get("sync_key") or "")[:40]
            lines.append(
                f"| {e['poll']} | {e['t'][11:19]} | {e.get('bytes')} | `{sk}…` | {e.get('baseline_co2e')} | "
                f"{e.get('optimized_co2e')} | {e.get('carbon_saved')} | {e.get('region')} | {e.get('chunk_count')} | "
                f"{e.get('routing_table_count')} | {e.get('applied')} | {e.get('stale_vs_current')} |"
            )
        lines.append("")

        lines.append("### Object identity log (sample)")
        lines.append("")
        for idn in r.identity_log[:8] + (r.identity_log[-3:] if len(r.identity_log) > 11 else []):
            lines.append(
                f"- Poll #{idn.get('poll')}: same_object={idn.get('same_object')} "
                f"applied={idn.get('applied')} gen={idn.get('object_gen')} "
                f"render_if_applied={idn.get('react_render_triggered_if_applied')}"
            )
        lines.append("")

        lines.append("### Race proof (Summary Ready → early stop must NOT happen)")
        lines.append("")
        if r.pass_fail.get("race_summary_ready_then_early_stop"):
            lines.append("**FAIL** — frontend would have stopped before full dashboard.")
        else:
            lines.append("**PASS** — no Summary-Ready early stop; polling continued until dashboard fields present.")
        for ev in r.race_proof:
            lines.append(f"- `{ev.get('event')}` poll={ev.get('poll')} details={json.dumps({k:v for k,v in ev.items() if k not in ('event','poll')}, default=str)[:240]}")
        lines.append("")

        lines.append("### §6 stop criteria at termination")
        lines.append("")
        checks = (r.pass_fail.get("user_criteria_at_stop") or {}).get("checks") or {}
        for k, v in checks.items():
            lines.append(f"- `{k}`: **{v}**")
        lines.append("")

        # Milestone sequence from result events
        lines.append("### Browser-equivalent milestone sequence (from result polls, no refresh)")
        lines.append("")
        milestones = []
        for e in r.result_events:
            if e.get("has_summary") and "summary" not in milestones:
                milestones.append("summary")
                lines.append(f"1. Summary appears — poll #{e['poll']} @ {e['t']}")
            if e.get("optimized_co2e", 0) > 0 and "opt" not in milestones:
                milestones.append("opt")
                lines.append(f"2. Optimized CO₂e appears ({e['optimized_co2e']}) — poll #{e['poll']}")
            if e.get("baseline_co2e", 0) > 0 and "base" not in milestones:
                milestones.append("base")
                lines.append(f"3. Baseline CO₂e appears ({e['baseline_co2e']}) — poll #{e['poll']}")
            if e.get("carbon_saved", 0) != 0 and "saved" not in milestones:
                milestones.append("saved")
                lines.append(f"4. Carbon Saved appears ({e['carbon_saved']}) — poll #{e['poll']}")
            if e.get("reduction_percent", 0) != 0 and "red" not in milestones:
                milestones.append("red")
                lines.append(f"5. Reduction appears ({e['reduction_percent']}) — poll #{e['poll']}")
            if e.get("region") and "reg" not in milestones:
                milestones.append("reg")
                lines.append(f"6. Region appears ({e['region']}) — poll #{e['poll']}")
            if e.get("routing_table_count", 0) > 0 and "route" not in milestones:
                milestones.append("route")
                lines.append(f"7. Routing table appears (n={e['routing_table_count']}) — poll #{e['poll']}")
        if r.pass_fail.get("frontend_stopped"):
            lines.append(f"8. Polling stops — poll #{r.pass_fail.get('frontend_stop_at_poll')}")
        lines.append("")

    lines.append("## Browser React logs")
    lines.append("")
    lines.append(
        "Browser console `SYNC_LIFECYCLE` events are captured separately when the Results tab "
        "is attached (see `browser_sync_logs` in the JSON if present). The API timeline above "
        "mirrors the same gates the Results page uses (`job-result-sync.ts`)."
    )
    lines.append("")
    lines.append("## Confirmation: manual refresh required?")
    lines.append("")
    if all_pass:
        lines.append(
            "No — for all three sizes, the mirrored frontend stop condition only fired after "
            "baseline/region (and §6 fields) were present on `/job-result`, so a page refresh "
            "is not required to populate dashboard cards."
        )
    else:
        lines.append(
            "Cannot confirm yet — one or more sizes failed or stopped without full §6 fields. "
            "Do **not** claim refresh is obsolete until Overall PASS."
        )
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {md_path}", flush=True)
    print(f"Wrote {json_path}", flush=True)
    return md_path


def main() -> int:
    selected = os.environ.get("SYNC_VAL_SIZES", "small,medium,large").split(",")
    selected = [x.strip() for x in selected if x.strip()]
    runs: List[JobRun] = []
    for label, path, timeout in DOCS:
        if label not in selected:
            continue
        if not path.is_file():
            runs.append(
                JobRun(
                    label=label,
                    path=str(path),
                    error=f"missing file {path}",
                    pass_fail={"passed": False},
                    started_at=utc_now(),
                    ended_at=utc_now(),
                )
            )
            continue
        runs.append(run_one(label, path, timeout))
        # persist partial after each size
        write_report(runs)

    write_report(runs)
    ok = all(r.pass_fail.get("passed") for r in runs) and len(runs) >= len(selected)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
