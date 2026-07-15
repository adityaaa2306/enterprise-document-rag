import json
from pathlib import Path

p = sorted(Path("eval_out").glob("consistency_medium_*.json"), key=lambda x: x.stat().st_mtime)[-1]
d = json.loads(p.read_text(encoding="utf-8"))
print("job", d["job_id"])
print("max_baseline", d["max_baseline_seen"])
print("client_regressions", json.dumps(d["client_regressions"], indent=2))
print("\nWRITES:")
for w in d["writes"]:
    print(
        f"R{w['revision']:02d} t={w['t_iso']} writer={w['writer']}\n"
        f"   key={w['sync_key']}\n"
        f"   prev={w['sync_key_prev']}\n"
        f"   viol={w['monotonicity_violations']} removed={w['keys_removed_sample'][:15]}\n"
        f"   extra={w.get('extra')}"
    )
print("\nRESULT timeline:")
for t in d["timeline"]:
    if t.get("kind") != "RESULT":
        continue
    print(
        f"poll {t['poll']:3d} {t['t'][11:19]} base={t.get('baseline')} "
        f"opt={t.get('optimized')} region={t.get('region')} bg={t.get('bg_phase')} "
        f"reg={t.get('regressed_from_max_baseline')} key={t.get('sync_key')}"
    )
print("\nSTATUS around summary/search:")
for t in d["timeline"]:
    if t.get("kind") != "STATUS":
        continue
    msg = (t.get("message") or "").lower()
    if "summary" in msg or "search" in msg or t.get("metrics_ready") or t.get("summary_ready"):
        print(
            f"poll {t['poll']:3d} {t['t'][11:19]} prog={t.get('progress')} "
            f"sum={t.get('summary_ready')} met={t.get('metrics_ready')} bg={t.get('background_phase')} "
            f"msg={(t.get('message') or '')[:70]}"
        )
