#!/usr/bin/env python3
"""Exercise the bounded telemetry sink with a slow-consumer equivalent."""

from __future__ import annotations

import argparse
import json

from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher


def run(messages: int, capacity: int) -> dict[str, int]:
    publisher = InMemoryTelemetryPublisher(max_messages=capacity)
    for index in range(messages):
        publisher.publish({"sequence": index})
    return {
        "published": publisher.publish_count,
        "retained": len(publisher.messages),
        "dropped": publisher.dropped_count,
        "capacity": capacity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=10_000)
    parser.add_argument("--capacity", type=int, default=256)
    args = parser.parse_args()
    if args.messages < 1 or args.capacity < 1:
        parser.error("messages and capacity must be positive")
    print(json.dumps(run(args.messages, args.capacity), sort_keys=True))


if __name__ == "__main__":
    main()
