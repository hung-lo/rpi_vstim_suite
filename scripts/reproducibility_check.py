#!/usr/bin/env python3
"""Check deterministic software plans without creating a hardware session."""

from __future__ import annotations

import argparse
import hashlib
import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import build_simulation_plan


def run(seed: int) -> dict[str, object]:
    config = config_from_mapping({"protocol": {"name": "natural-images"}})
    first = build_simulation_plan(config, protocol_name="natural-images", seed=seed)
    second = build_simulation_plan(config, protocol_name="natural-images", seed=seed)
    if first.stable_json() != second.stable_json():
        raise AssertionError("same seed produced different plan JSON")
    return {
        "seed": seed,
        "stable_json_bytes": len(first.stable_json().encode()),
        "event_count": len(first.events),
        "plan_digest": hashlib.sha256(first.stable_json().encode()).hexdigest(),
        "identical": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=123)
    args = parser.parse_args()
    print(json.dumps(run(args.seed), sort_keys=True))


if __name__ == "__main__":
    main()
