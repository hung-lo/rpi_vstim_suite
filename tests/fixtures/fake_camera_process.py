#!/usr/bin/env python3
"""Tiny subprocess camera fixture for lifecycle tests."""

from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mode",
        choices=("normal", "fail", "no-growth", "stall", "ignore-terminate"),
        default="normal",
    )
    parser.add_argument("--interval", type=float, default=0.01)
    args = parser.parse_args()
    if args.mode == "fail":
        raise SystemExit(3)
    if args.mode == "ignore-terminate":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.mode not in {"no-growth", "fail"}:
        output.write_bytes(b"frame\n")
    while True:
        if args.mode == "normal":
            with output.open("ab") as handle:
                handle.write(b"frame\n")
                handle.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
