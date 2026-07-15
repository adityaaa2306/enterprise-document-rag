#!/usr/bin/env python3
"""Merge small + medium/large validation artifacts into the final report."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "eval_out"


def main() -> None:
    def load(name: str):
        return json.loads((OUT / name).read_text(encoding="utf-8-sig"))

    small = load("frontend_state_sync_small.json")
    ml = load("frontend_state_sync_medium_large.json")
    browser_small = load("browser_sync_small.json")
    browser_large = load("browser_sync_large.json")

    runs = []
    runs.extend(small["runs"])
    runs.extend(ml["runs"])

    for r in runs:
        if r["label"] == "small":
            r["browser"] = browser_small
        elif r["label"] == "large":
            r["browser"] = browser_large
        elif r["label"] == "medium":
            r["browser"] = {
                "manual_refresh": False,
                "cold_load_after_complete": {
                    "banner": "Summary Ready · Finishing analytics…",
                    "cards_populated": False,
                    "api_note": (
                        "status.metrics_ready=true + background_phase=search_ready but "
                        "/job-result still Summary Ready stub (baseline=0, region=null)"
                    ),
                },
            }

    overall_pass = all(r.get("pass_fail", {}).get("passed") for r in runs) and len(runs) == 3
    merged = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api": "http://127.0.0.1:8000",
        "overall_pass": overall_pass,
        "runs": runs,
        "gaps": [
            "Product code does not reject older sync_key / updated_at / revision (always applies OK /job-result).",
            "Medium job showed result richness regression after FE-mirror stop (POST_STOP snapshots returned stub).",
            "isMetricsReadyFromResult can stop when carbon is populated even if status.metrics_ready/search_ready are false.",
        ],
    }
    (OUT / "frontend_state_sync_validation.json").write_text(
        json.dumps(merged, indent=2), encoding="utf-8"
    )

    lines: list[str] = []
    A = lines.append
    A("# Frontend State Sync Validation")
    A("")
    A(f"- Generated: `{merged['generated_at']}`")
    A(
        "- Method: live `/summarize` uploads + dense `/job-status` & `/job-result` polling "
        "mirroring `frontend/lib/job-result-sync.ts`, plus Results page left open in browser "
        "(no `location.reload`)."
    )
    A("- Product code was **not** modified for this validation.")
    A("")
    A("## Verdict")
    A("")
    overall = "PASS" if overall_pass else "FAIL"
    A(f"**Overall: {overall}**")
    A("")
    A(
        "Success requires **all three** sizes to pass without a browser refresh. "
        "That bar is **not** met."
    )
    A("")
    A(
        "| Size | Doc | Job | Passed | FE stop poll | Early stop before section 6? | "
        "Sync keys | Browser cards without refresh |"
    )
    A("|------|-----|-----|--------|--------------|------------------------------|-----------|-------------------------------|")
    for r in runs:
        pf = r.get("pass_fail") or {}
        br = r.get("browser") or {}
        cards = "yes" if br.get("cards") else "no"
        path = Path(r["path"]).name if r.get("path") else ""
        A(
            f"| {r['label']} | `{path}` | `{r.get('job_id','')}` | **{pf.get('passed')}** | "
            f"{pf.get('frontend_stop_at_poll')} | {pf.get('race_summary_ready_then_early_stop')} | "
            f"{len(pf.get('sync_key_evolution') or [])} | {cards} |"
        )
    A("")

    A("## What section 6 requires to stop polling")
    A("")
    A(
        "`status==complete` AND `summary_ready` AND `metrics_ready` AND `search_ready` AND "
        "`baseline>0` AND `optimized>0` AND region AND routing table."
    )
    A("")
    A(
        "Frontend mirror stop (`finishMetrics`) currently stops when `isMetricsReadyFromResult` "
        "is true (baseline>0 AND region), even if status flags lag or flip."
    )
    A("")

    A("## Gap: stale / older payload rejection (item 5)")
    A("")
    A("**Not implemented in product code.** Every HTTP 200 `/job-result` is cloned and applied.")
    A("")
    A(
        "Observed on **medium**: after a rich result (baseline~118, India) later fetches "
        "returned a **stub** again (baseline=0, phase=queued). Harness recorded this; "
        "product has no older-`sync_key` guard."
    )
    A("")

    for r in runs:
        pf = r.get("pass_fail") or {}
        A(f"## Run: {r['label']}")
        A("")
        A(f"- job_id: `{r.get('job_id')}`")
        A(f"- guest: `{r.get('guest_id')}`")
        A(f"- window: {r.get('started_at')} → {r.get('ended_at')}")
        A(f"- status polls: {len(r.get('status_events') or [])}")
        A(f"- result fetches: {len(r.get('result_events') or [])}")
        A(f"- passed: **{pf.get('passed')}**")
        A("")
        A("### Sync key evolution")
        A("")
        for i, k in enumerate(pf.get("sync_key_evolution") or [], 1):
            A(f"{i}. `{k}`")
        A("")
        A("### Milestone sequence (from result polls)")
        A("")
        milestones: list[str] = []

        def add(tag: str, text: str, e: dict) -> None:
            if tag not in milestones:
                milestones.append(tag)
                A(f"- {text} — poll #{e['poll']} @ {e['t']}")

        for e in r.get("result_events") or []:
            if e.get("has_summary"):
                add("summary", "Summary present", e)
            if (e.get("optimized_co2e") or 0) > 0:
                add("opt", f"Optimized CO₂e = {e.get('optimized_co2e')}", e)
            if (e.get("baseline_co2e") or 0) > 0:
                add("base", f"Baseline CO₂e = {e.get('baseline_co2e')}", e)
            if (e.get("carbon_saved") or 0) != 0:
                add("saved", f"Carbon saved = {e.get('carbon_saved')}", e)
            if (e.get("reduction_percent") or 0) != 0:
                add("red", f"Reduction = {e.get('reduction_percent')}%", e)
            if e.get("region"):
                add(
                    "reg",
                    f"Region = {e.get('region')} (grid {e.get('grid_intensity')})",
                    e,
                )
            if (e.get("routing_table_count") or 0) > 0:
                add("route", f"Routing rows = {e.get('routing_table_count')}", e)
        if pf.get("frontend_stopped"):
            A(f"- Polling stop (FE mirror) — poll #{pf.get('frontend_stop_at_poll')}")
        A("")
        A("### Section 6 checks at FE stop")
        A("")
        checks = (pf.get("user_criteria_at_stop") or {}).get("checks") or {}
        for k, v in checks.items():
            A(f"- `{k}`: **{v}**")
        A("")
        A("### Race proof")
        A("")
        if pf.get("race_summary_ready_then_early_stop"):
            A("**FAIL** — FE mirror would stop before all section 6 flags were true.")
        else:
            A("**PASS** — no Summary-Ready-only early stop relative to section 6.")
        for ev in (r.get("race_proof") or [])[:8]:
            detail = {k: v for k, v in ev.items() if k not in ("event", "poll", "checks")}
            A(
                f"- `{ev.get('event')}` poll={ev.get('poll')} → "
                f"{json.dumps(detail, default=str)[:220]}"
            )
        A("")
        A("### Object identity (sample)")
        A("")
        idn = r.get("identity_log") or []
        sample = idn[:5] + (idn[-2:] if len(idn) > 7 else [])
        for row in sample:
            A(
                f"- Poll #{row.get('poll')}: same_object={row.get('same_object')} "
                f"sync_key_changed={row.get('sync_key_changed')} applied={row.get('applied')} "
                f"gen={row.get('object_gen')} render_if_applied={row.get('react_render_triggered_if_applied')}"
            )
        A("")
        A("### Status timeline (compressed)")
        A("")
        A(
            "| poll | t | progress | status | message | summary_ready | metrics_ready | "
            "search_ready | bg |"
        )
        A("|------|---|----------|--------|---------|---------------|---------------|--------------|----|")
        sts = r.get("status_events") or []
        idxs = set(range(min(3, len(sts)))) | set(range(max(0, len(sts) - 5), len(sts)))
        for i, s in enumerate(sts):
            msg = (s.get("message") or "").lower()
            if (
                "summary ready" in msg
                or "search ready" in msg
                or s.get("summary_ready")
                or s.get("metrics_ready")
            ):
                idxs.add(i)
        for i in sorted(idxs):
            s = sts[i]
            msg = (s.get("message") or "").replace("|", "/")[:48]
            A(
                f"| {s.get('poll')} | {str(s.get('t',''))[11:19]} | {s.get('progress')} | "
                f"{s.get('status')} | {msg} | {s.get('summary_ready')} | {s.get('metrics_ready')} | "
                f"{s.get('search_ready')} | {s.get('background_phase')} |"
            )
        A("")
        A("### Result timeline")
        A("")
        A(
            "| poll | t | bytes | baseline | optimized | saved | region | chunks | routing | "
            "sync_key (trim) | applied | stale? |"
        )
        A(
            "|------|---|-------|----------|-----------|-------|--------|--------|---------|-----------------|---------|--------|"
        )
        for e in r.get("result_events") or []:
            sk = (e.get("sync_key") or "")[:36]
            A(
                f"| {e.get('poll')} | {str(e.get('t',''))[11:19]} | {e.get('bytes')} | "
                f"{round(e.get('baseline_co2e') or 0, 2)} | {round(e.get('optimized_co2e') or 0, 2)} | "
                f"{round(e.get('carbon_saved') or 0, 2)} | {e.get('region')} | {e.get('chunk_count')} | "
                f"{e.get('routing_table_count')} | `{sk}` | {e.get('applied')} | {e.get('stale_vs_current')} |"
            )
        A("")
        A("### Browser")
        A("")
        br = r.get("browser") or {}
        if br.get("cards"):
            A(f"- Manual refresh used: **{br.get('manual_refresh')}**")
            A(f"- Banner: `{br.get('banner')}`")
            for k, v in (br.get("cards") or {}).items():
                A(f"- {k}: **{v}**")
            if br.get("screenshot"):
                A(f"- Screenshot: `{br.get('screenshot')}`")
        else:
            A("```json")
            A(json.dumps(br, indent=2)[:1200])
            A("```")
        A("")

    A("## Proof matrix vs requested items")
    A("")
    A("| # | Requirement | Small | Medium | Large |")
    A("|---|-------------|-------|--------|-------|")
    A("| 1 | Timestamped /job-status timeline | yes | yes | yes |")
    A("| 2 | Timestamped /job-result + sync_key fields | yes | yes | yes |")
    A("| 3 | React-mirror state (stop/continue) | yes | yes | yes |")
    A("| 4 | Object identity replaced each apply | yes (gen++) | yes | yes |")
    A("| 5 | Older sync_key ignored | **no product logic** | regression observed | no stale seen |")
    A("| 6 | Stop only when all section 6 true | pass | **fail** | pass |")
    A("| 7 | No Summary→stop→miss final | pass | **fail** | pass |")
    A("| 8 | Browser fills without refresh | **pass** | **fail** | **pass** |")
    A("| 9 | Stress 3 sizes identical | — | — | overall **fail** |")
    A("")
    A("## Confirmation: is manual refresh obsolete?")
    A("")
    A(
        "**No — not yet.** Small and large automatically populated dashboard cards with the "
        "Results page left open. Medium did **not** meet section 6 stop criteria and currently serves "
        "a stub `/job-result` while status claims Search Ready."
    )
    A("")
    A("## Artifacts")
    A("")
    A("- `frontend_state_sync_validation.json` (merged)")
    A("- `frontend_state_sync_small.json`")
    A("- `frontend_state_sync_medium_large.json`")
    A("- `browser_sync_small.json` / `browser_sync_large.json`")
    A("- `sync-val-small-dashboard.png` / `sync-val-large-dashboard.png`")
    A("- Harness: `backend/scripts/validate_frontend_state_sync.py`")
    A("")

    md = OUT / "FRONTEND_STATE_SYNC_VALIDATION.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print("overall", overall)
    print("wrote", md)
    print("jobs", [(r["label"], r.get("job_id"), r.get("pass_fail", {}).get("passed")) for r in runs])


if __name__ == "__main__":
    main()
