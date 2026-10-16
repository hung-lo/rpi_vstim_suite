#!/usr/bin/env python3
"""Check deterministic software plans without creating a hardware session."""

from __future__ import annotations

import argparse
import hashlib
import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import build_simulation_plan


def run(seed: int, count: int = 1) -> dict[str, object]:
    config = config_from_mapping({"protocol": {"name": "natural-images"}})
    last = None
    for current_seed in range(seed, seed + count):
        first = build_simulation_plan(config, protocol_name="natural-images", seed=current_seed)
        second = build_simulation_plan(config, protocol_name="natural-images", seed=current_seed)
        if first.stable_json() != second.stable_json():
            raise AssertionError(f"same seed produced different plan JSON: {current_seed}")
        last = first
    assert last is not None
    return {
        "seed": seed,
        "seeds_checked": count,
        "stable_json_bytes": len(last.stable_json().encode()),
        "event_count": len(last.events),
        "plan_digest": hashlib.sha256(last.stable_json().encode()).hexdigest(),
        "identical": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--seeds", type=int, default=100)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("seeds must be positive")
    print(json.dumps(run(args.seed, args.seeds), sort_keys=True))


if __name__ == "__main__":
    main()
