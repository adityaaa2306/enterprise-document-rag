"""Probe Gemini key + model quotas (never prints the key)."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import httpx


def load_dotenv(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    key = os.environ.get("GEMINI_API_KEY") or ""
    print(f"key_len={len(key)} key_sha8={hashlib.sha256(key.encode()).hexdigest()[:8]}")
    if not key:
        print("FAIL: no key")
        return 1

    print("waiting 60s for quota window...")
    time.sleep(60)

    models = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
    ]
    payload = {
        "contents": [{"parts": [{"text": "Reply with exactly: GEMINI_OK"}]}],
        "generationConfig": {"maxOutputTokens": 64, "temperature": 0},
    }
    ok_models = []
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        try:
            r = httpx.post(url, params={"key": key}, json=payload, timeout=45.0)
            data = r.json()
            if r.status_code == 200:
                text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                print(f"{m}: OK http=200 reply={text!r}")
                ok_models.append(m)
            else:
                err = data.get("error") or {}
                msg = (err.get("message") or "").replace("\n", " ")[:180]
                print(f"{m}: FAIL http={r.status_code} {err.get('status')} {msg}")
        except Exception as e:
            print(f"{m}: FAIL {type(e).__name__}: {e}")

    print("ok_models=", ok_models)
    return 0 if ok_models else 2


if __name__ == "__main__":
    raise SystemExit(main())
