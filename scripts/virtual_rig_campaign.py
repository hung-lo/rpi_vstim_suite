#!/usr/bin/env python3
"""Run real subprocess-camera virtual sessions across all protocols."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rpi_vstim.core.session import inspect_session
from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.virtual_rig import run_virtual_session


PROTOCOLS = ("natural-images", "reward-conditioning", "spout-training", "drifting-gratings", "retinotopy")


def run(sessions: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-virtual-campaign-") as temporary:
        root = Path(temporary)
        outcomes: dict[str, int] = {}
        inspected = 0
        for index in range(sessions):
            protocol = PROTOCOLS[index % len(PROTOCOLS)]
            config = config_from_mapping({
                "paths": {"output_root": root},
                "protocol": {"name": protocol, "version": "software-groundwork"},
                "cameras": {"devices": [
                    {"id": "face", "role": "face", "required": True, "device": "virtual-face"},
                    {"id": "behavior", "role": "behavior", "device": "virtual-behavior"},
                ]},
            })
            result = run_virtual_session(
                config,
                protocol_name=protocol,
                session_id=f"virtual-{index:04d}",
                seed=index,
            )
            outcomes[result.final_state.value] = outcomes.get(result.final_state.value, 0) + 1
            report = inspect_session(result.session.context.session_root)
            assert report["status"] == "COMPLETE" and not report["corrupt_artifacts"]
            inspected += 1
        return {"sessions": sessions, "outcomes": outcomes, "inspected": inspected}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=50)
    args = parser.parse_args()
    if args.sessions < 1:
        parser.error("sessions must be positive")
    print(json.dumps(run(args.sessions), sort_keys=True))


if __name__ == "__main__":
    main()
