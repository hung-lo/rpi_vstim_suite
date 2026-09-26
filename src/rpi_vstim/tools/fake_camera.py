"""Deterministic subprocess camera emulator for virtual-rig tests only."""

from __future__ import annotations

import argparse
import random
import signal
import sys
import time
from pathlib import Path


MODES = (
    "normal",
    "delayed-startup",
    "fail",
    "no-growth",
    "no-output",
    "zero-output",
    "stall",
    "stderr",
    "ignore-terminate",
    "delayed-exit",
    "truncated",
    "seeded-failure",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=MODES, default="normal")
    parser.add_argument("--interval", type=float, default=0.01)
    parser.add_argument("--startup-delay", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if args.mode in {"fail", "seeded-failure"}:
        if args.mode == "stderr":
            print("fake camera diagnostic", file=sys.stderr)
        if args.mode == "seeded-failure" and random.Random(args.seed).random() >= 0.2:
            pass
        else:
            print("fake camera failure", file=sys.stderr)
            return 3
    if args.mode == "stderr":
        print("fake camera diagnostic", file=sys.stderr)
    if args.mode == "ignore-terminate":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    elif args.mode == "delayed-exit":
        def delayed_stop(_signum, _frame):
            time.sleep(0.2)
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, delayed_stop)
    if args.mode == "delayed-startup":
        time.sleep(args.startup_delay)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.mode in {"no-output", "no-growth"}:
        pass
    elif args.mode == "zero-output":
        output.touch()
    elif args.mode in {"normal", "stall", "stderr", "delayed-exit", "ignore-terminate"}:
        output.write_bytes(b"frame\n")
    elif args.mode == "truncated":
        output.write_bytes(b"partial")
    while True:
        if args.mode in {"normal", "stderr", "delayed-exit", "ignore-terminate"}:
            with output.open("ab") as handle:
                handle.write(b"frame\n")
                handle.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
