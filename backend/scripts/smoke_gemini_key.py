"""Smoke-test GEMINI_API_KEY from backend/.env (does not print the key)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx


def load_dotenv(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def main() -> int:
    root = Path(__file__).resolve().parents[1]  # backend/
    load_dotenv(root / ".env")
    key = os.environ.get("GEMINI_API_KEY") or ""
    model = os.environ.get("GRAPHIFY_GEMINI_MODEL") or "gemini-2.5-flash"
    print(f"key_present={bool(key)} key_len={len(key)}")
    print(f"model={model}")
    if not key:
        print("FAIL: GEMINI_API_KEY not set")
        return 1

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "Reply with exactly: GEMINI_OK. No other words.",
                    }
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 256,
            "temperature": 0,
        },
    }
    try:
        r = httpx.post(
            url,
            params={"key": key},
            json=payload,
            timeout=30.0,
        )
    except Exception as e:
        print(f"FAIL: request error {type(e).__name__}: {e}")
        return 2

    print(f"http_status={r.status_code}")
    try:
        data = r.json()
    except Exception:
        print(f"FAIL: non-JSON body: {r.text[:300]}")
        return 3

    if r.status_code != 200:
        err = data.get("error") if isinstance(data, dict) else data
        # Avoid dumping anything that might echo the key
        print("FAIL: API error")
        print(json.dumps(err, indent=2)[:800] if err else r.text[:400])
        return 4

    text = ""
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        print("FAIL: unexpected response shape")
        print(json.dumps(data, indent=2)[:800])
        return 5

    print(f"model_reply={text!r}")
    ok = "GEMINI_OK" in (text or "").upper().replace(" ", "")
    print("PASS" if ok or text.strip() else "PASS_WITH_REPLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
