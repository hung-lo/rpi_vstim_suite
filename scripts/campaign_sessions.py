#!/usr/bin/env python3
"""Run a bounded multi-protocol session campaign without hardware."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session


PROTOCOLS = ("natural-images", "reward-conditioning", "spout-training", "drifting-gratings", "retinotopy")


def run(count: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-campaign-") as temporary:
        root = Path(temporary)
        completed = 0
        by_protocol: dict[str, int] = {name: 0 for name in PROTOCOLS}
        for index in range(count):
            protocol = PROTOCOLS[index % len(PROTOCOLS)]
            values: dict[str, object] = {
                "paths": {"output_root": root},
                "protocol": {"name": protocol, "version": "software-groundwork"},
            }
            if index % 4 == 0:
                values["cameras"] = {
                    "devices": [
                        {"id": "face", "role": "face", "required": True, "device": "face-id"},
                        {"id": "behavior", "role": "behavior", "device": "behavior-id"},
                    ]
                }
            config = config_from_mapping(values)
            result = run_simulated_session(
                config,
                protocol_name=protocol,
                session_id=f"campaign-{index:04d}",
                seed=index,
            )
            if not result.ok:
                raise RuntimeError(f"campaign session failed: {protocol} {index}: {result.error}")
            completed += 1
            by_protocol[protocol] += 1
        return {"requested": count, "completed": completed, "by_protocol": by_protocol}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=100)
    args = parser.parse_args()
    if args.sessions < 1:
        parser.error("--sessions must be positive")
    print(json.dumps(run(args.sessions), sort_keys=True))


if __name__ == "__main__":
    main()
