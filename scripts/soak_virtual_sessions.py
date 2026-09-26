#!/usr/bin/env python3
"""Run a bounded repeated session lifecycle campaign outside pytest."""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.leaks import delta, snapshot
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


def run(sessions: int) -> dict[str, object]:
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
    before = snapshot()
    tracemalloc.start()
    started = time.monotonic()
    outcomes: dict[str, int] = {}
    peak_rss = 0
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-soak-") as temporary:
        root = Path(temporary)
        for index in range(sessions):
            config = config_from_mapping({"paths": {"output_root": root}})
            result = run_simulated_session(
                config,
                plan=plan,
                session_id=f"soak-{index:05d}",
                seed=index,
            )
            outcomes[result.final_state.value] = outcomes.get(result.final_state.value, 0) + 1
            peak_rss = max(peak_rss, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        disk_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after = snapshot()
    leak = delta(before, after)
    if outcomes.get("COMPLETE", 0) != sessions or any(value for value in leak.values() if value not in (None, 0)):
        raise AssertionError({"outcomes": outcomes, "leak": leak})
    return {
        "sessions": sessions,
        "duration_s": round(time.monotonic() - started, 3),
        "outcomes": outcomes,
        "leak": leak,
        "tracemalloc_current_bytes": current,
        "tracemalloc_peak_bytes": peak,
        "peak_rss_kb": peak_rss,
        "temporary_disk_bytes": disk_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=10_000)
    args = parser.parse_args()
    if args.sessions < 1:
        parser.error("sessions must be positive")
    print(json.dumps(run(args.sessions), sort_keys=True))


if __name__ == "__main__":
    main()
