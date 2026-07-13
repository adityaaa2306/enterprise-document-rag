#!/usr/bin/env python3
"""
Standalone NIM model health probe — does NOT go through the app pipeline.

Calls each candidate model with a trivial prompt, 3–5 times, and reports
success/failure + wall latency. Used to decide circuit-breaker vs config fix.

Usage (from backend/):
  .\\.venv\\Scripts\\python.exe scripts\\probe_nim_models.py
  .\\.venv\\Scripts\\python.exe scripts\\probe_nim_models.py --attempts 5 --timeout 90
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Load backend/.env without importing the app
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

from openai import OpenAI
import httpx


DEFAULT_MODELS = [
    "google/gemma-4-31b-it",
    "meta/llama-3.2-3b-instruct",
    # Known-good control (should succeed if the endpoint/key are fine)
    "mistralai/ministral-14b-instruct-2512",
]

MESSAGES = [
    {"role": "system", "content": "Reply with exactly one short sentence."},
    {"role": "user", "content": "Say hello in five words or fewer."},
]


def probe_once(client: OpenAI, model_id: str, timeout_sec: float) -> dict:
    t0 = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=model_id,
            messages=MESSAGES,
            temperature=0.0,
            max_tokens=32,
            timeout=httpx.Timeout(timeout_sec, connect=15.0),
        )
        text = (completion.choices[0].message.content or "").strip()
        ms = (time.perf_counter() - t0) * 1000.0
        ok = bool(text)
        return {
            "ok": ok,
            "latency_ms": round(ms, 1),
            "error": None if ok else "empty_response",
            "preview": (text[:80] + ("…" if len(text) > 80 else "")) if text else "",
            "http_status": 200 if ok else None,
        }
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000.0
        status = getattr(e, "status_code", None)
        err = f"{type(e).__name__}: {e}"
        # Classify common failure modes
        kind = "error"
        low = err.lower()
        if "timeout" in low or "timed out" in low:
            kind = "timeout"
        elif status == 404 or "404" in err or "not found" in low or "does not exist" in low:
            kind = "not_found"
        elif status == 429 or "429" in err:
            kind = "rate_limit"
        elif status is not None and int(status) >= 500:
            kind = f"http_{status}"
        elif status is not None:
            kind = f"http_{status}"
        return {
            "ok": False,
            "latency_ms": round(ms, 1),
            "error": err[:300],
            "preview": "",
            "http_status": status,
            "kind": kind,
        }


def main() -> int:
    p = argparse.ArgumentParser(description="Probe NIM model IDs directly")
    p.add_argument("--attempts", type=int, default=4, help="Attempts per model (default 4)")
    p.add_argument("--timeout", type=float, default=90.0, help="Per-call timeout seconds")
    p.add_argument(
        "--models",
        nargs="*",
        default=DEFAULT_MODELS,
        help="Model IDs to probe",
    )
    args = p.parse_args()

    api_key = os.environ.get("NVIDIA_API_KEY") or ""
    base_url = (os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1").rstrip("/")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not set (load backend/.env)")
        return 2

    print(f"NIM probe base_url={base_url}")
    print(f"timeout={args.timeout}s attempts_per_model={args.attempts}")
    print(f"models={args.models}")
    print("-" * 72)

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=httpx.Timeout(args.timeout, connect=15.0),
        max_retries=0,
    )

    summary = {}
    for model_id in args.models:
        print(f"\n=== {model_id} ===")
        results = []
        for i in range(1, args.attempts + 1):
            print(f"  attempt {i}/{args.attempts} …", flush=True)
            r = probe_once(client, model_id, args.timeout)
            results.append(r)
            status = "OK" if r["ok"] else f"FAIL({r.get('kind') or 'error'})"
            print(
                f"  → {status}  latency_ms={r['latency_ms']:.0f}  "
                f"http={r.get('http_status')}  "
                f"{('preview=' + repr(r['preview'])) if r['ok'] else ('error=' + str(r['error'])[:160])}"
            )
            # Brief pause between attempts to avoid burst rate-limits
            if i < args.attempts:
                time.sleep(1.0)

        oks = [r for r in results if r["ok"]]
        fails = [r for r in results if not r["ok"]]
        summary[model_id] = {
            "ok": len(oks),
            "fail": len(fails),
            "latencies_ok_ms": [r["latency_ms"] for r in oks],
            "latencies_all_ms": [r["latency_ms"] for r in results],
            "kinds": [r.get("kind") or ("ok" if r["ok"] else "error") for r in results],
        }
        if oks:
            print(
                f"  summary: {len(oks)}/{args.attempts} ok  "
                f"ok_latency mean={sum(summary[model_id]['latencies_ok_ms'])/len(oks):.0f}ms  "
                f"min={min(summary[model_id]['latencies_ok_ms']):.0f}  "
                f"max={max(summary[model_id]['latencies_ok_ms']):.0f}"
            )
        else:
            print(f"  summary: 0/{args.attempts} ok  kinds={summary[model_id]['kinds']}")

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    for model_id, s in summary.items():
        n = s["ok"] + s["fail"]
        rate = s["ok"] / n if n else 0.0
        if rate == 0:
            label = "BROKEN / unreachable (0 successes)"
        elif rate < 0.5:
            label = "UNHEALTHY (mostly failing)"
        elif rate < 1.0:
            label = "FLAKY (sometimes works — breaker appropriate)"
        else:
            # Check if "working but very slow"
            mean = sum(s["latencies_ok_ms"]) / len(s["latencies_ok_ms"])
            if mean > 30000:
                label = f"SLOW-BUT-WORKING (mean {mean/1000:.1f}s) — breaker still useful"
            else:
                label = f"HEALTHY (mean {mean/1000:.1f}s)"
        print(f"  {model_id}: {s['ok']}/{n} ok → {label}")
        print(f"    kinds={s['kinds']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
