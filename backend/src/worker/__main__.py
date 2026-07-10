"""python -m src.worker"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Green Agentic durable job worker")
    parser.add_argument("--worker-id", default=None, help="Override WORKER_ID")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim/process at most one job then exit (tests / debug)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    from src.core.config import settings

    # Worker: JWT + prod safety required; CORS not required (no HTTP server)
    settings.validate_for_runtime(require_cors=False)

    from src.worker.loop import run_worker_forever

    run_worker_forever(worker_id=args.worker_id, once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
