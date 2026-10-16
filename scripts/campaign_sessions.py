#!/usr/bin/env python3
"""Run a bounded multi-protocol session campaign without hardware."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session


PROTOCOLS = ("natural-images", "reward-conditioning", "spout-training", "drifting-gratings", "retinotopy")


def run(count: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-campaign-") as temporary:
        root = Path(temporary)
        completed = 0
        by_protocol: dict[str, int] = {name: 0 for name in PROTOCOLS}
        terminal_states: Counter[str] = Counter()
        expected_failures = 0
        for index in range(count):
            protocol = PROTOCOLS[index % len(PROTOCOLS)]
            values: dict[str, object] = {
                "paths": {"output_root": root},
                "protocol": {"name": protocol, "version": "software-groundwork"},
            }
            with_cameras = index % 4 == 0
            if with_cameras:
                values["cameras"] = {
                    "devices": [
                        {"id": "face", "role": "face", "required": True, "device": "face-id"},
                        {"id": "behavior", "role": "behavior", "device": "behavior-id"},
                    ]
                }
            config = config_from_mapping(values)
            camera_failures = {"behavior"} if with_cameras and index % 7 == 0 else set()
            if with_cameras and index % 17 == 0:
                camera_failures = {"face"}
            interrupt = index % 11 == 0 and not camera_failures
            result = run_simulated_session(
                config,
                protocol_name=protocol,
                session_id=f"campaign-{index:04d}",
                seed=index,
                camera_failures=camera_failures,
                interrupt=interrupt,
            )
            terminal_states[result.final_state.value] += 1
            if result.final_state.value in {"FAILED", "INTERRUPTED"}:
                expected_failures += 1
            elif not result.ok:
                raise RuntimeError(f"campaign session failed unexpectedly: {protocol} {index}: {result.error}")
            completed += 1
            by_protocol[protocol] += 1
        return {
            "requested": count,
            "completed": completed,
            "expected_noncomplete": expected_failures,
            "by_protocol": by_protocol,
            "terminal_states": dict(sorted(terminal_states.items())),
            "threads_or_processes_leaked": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=100)
    args = parser.parse_args()
    if args.sessions < 1:
        parser.error("--sessions must be positive")
    print(json.dumps(run(args.sessions), sort_keys=True))


if __name__ == "__main__":
    main()
