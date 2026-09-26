#!/usr/bin/env python3
"""Small Mac-side profile for bounded plan generation."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import pstats
import tracemalloc
from io import StringIO

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import build_simulation_plan


def run(iterations: int) -> dict[str, object]:
    config = config_from_mapping({"protocol": {"name": "natural-images"}})
    profiler = cProfile.Profile()
    tracemalloc.start()
    profiler.enable()
    digest = ""
    event_count = 0
    for seed in range(iterations):
        plan = build_simulation_plan(config, protocol_name="natural-images", seed=seed)
        digest = hashlib.sha256(plan.stable_json().encode()).hexdigest()
        event_count += len(plan.events)
    profiler.disable()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    stream = StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(8)
    return {
        "iterations": iterations,
        "events": event_count,
        "last_plan_digest": digest,
        "peak_traced_bytes": peak,
        "top_functions": stream.getvalue(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    print(json.dumps(run(args.iterations), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
