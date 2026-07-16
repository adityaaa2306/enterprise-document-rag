#!/usr/bin/env python3
"""Fail if likely secrets appear in git-tracked files.

Usage (repo root):
  python scripts/scan_secrets.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# High-signal patterns only (avoid flooding on placeholders / tests).
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("NVIDIA live API key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "Hardcoded WattTime password assignment",
        re.compile(r'''WATTTIME_PASSWORD\s*=\s*["'](?!your_|YourStrong|<from |\$\{)[^"']{8,}["']'''),
    ),
    (
        "Hardcoded JWT secret assignment",
        re.compile(r'''JWT_SECRET_KEY\s*=\s*["'](?!test-|phase|abuse-|prod-secret|worker-prod|REPLACE)[^"']{16,}["']'''),
    ),
]

ALLOW_SUBSTRINGS = (
    "your_nvidia_api_key_here",
    "nvapi-test",
    "nvapi-key-",
    "REPLACE_WITH",
    "your_password",
    "YourStrongP@ssw0rd",
    "phase3-test-secret",
    "abuse-test-secret",
    "test-secret-key",
    "prod-secret-key",
    "worker-prod-secret",
)


def tracked_files() -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        stderr=subprocess.DEVNULL,
    )
    return [ROOT / p for p in out.decode("utf-8", errors="replace").split("\0") if p]


def allowed(line: str) -> bool:
    lower = line.lower()
    return any(s.lower() in lower for s in ALLOW_SUBSTRINGS)


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        # Skip lockfiles / binaries / large generated assets
        if path.suffix.lower() in {".lock", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".sqlite"}:
            continue
        if "node_modules" in path.parts or "yarn.lock" in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if allowed(line):
                continue
            for name, pat in PATTERNS:
                if pat.search(line):
                    rel = path.relative_to(ROOT).as_posix()
                    findings.append(f"{rel}:{i}: {name}")
                    break

    if findings:
        print("Potential secrets in tracked files:", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        return 1

    print("OK: no high-signal secrets found in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
