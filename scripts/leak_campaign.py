#!/usr/bin/env python3
"""Run repeated lifecycle variants and check thread/descriptor stability."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.leaks import delta, snapshot
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


def run(iterations: int) -> dict[str, object]:
    before = snapshot()
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-leak-") as temporary:
        root = Path(temporary)
        plan = build_plan(
            NaturalImageSettings(
                images=("a", "b"),
                trial_count=2,
                initial_gray_frames=1,
                final_gray_frames=1,
                image_duration_s=1 / 60,
                iti_frames=(1,),
            )
        )
        outcomes = {"COMPLETE": 0, "INTERRUPTED": 0, "FAILED": 0}
        for index in range(iterations):
            config = config_from_mapping({"paths": {"output_root": root}})
            result = run_simulated_session(
                config,
                plan=plan,
                session_id=f"session-{index:05d}",
                interrupt=index % 5 == 0,
                camera_failures=(),
                telemetry_failure=index % 11 == 0,
            )
            outcomes[result.final_state.value] = outcomes.get(result.final_state.value, 0) + 1
    after = snapshot()
    leak = delta(before, after)
    if (
        leak["thread_delta"] != 0
        or leak["file_descriptor_delta"] not in (None, 0)
        or leak["child_process_delta"] not in (None, 0)
    ):
        raise AssertionError(f"resource leak detected: {leak}")
    return {"iterations": iterations, "outcomes": outcomes, "leak": leak}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    print(json.dumps(run(args.iterations), sort_keys=True))


if __name__ == "__main__":
    main()
