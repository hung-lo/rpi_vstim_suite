#!/usr/bin/env python3
"""Deterministic state-machine stress for software-only bounded boundaries."""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.display.sequence import (
    BoundedFrameTransport,
    FrameTransportAborted,
    FrameTransportClosed,
    PreparedSequenceFrame,
)


def exercise_transport(rng: random.Random) -> None:
    transport = BoundedFrameTransport(rng.randint(1, 4))
    frame = PreparedSequenceFrame(0, "event", "sequence", "asset", "asset", "on", b"x")
    for _ in range(100):
        operation = rng.choice(("put", "get", "finish", "abort"))
        if operation == "put":
            try:
                transport.put(frame, timeout_s=0)
            except (FrameTransportClosed, FrameTransportAborted, TimeoutError):
                pass
        elif operation == "get":
            try:
                transport.get(timeout_s=0)
            except (FrameTransportAborted, TimeoutError):
                pass
        elif operation == "finish":
            transport.finish()
        else:
            transport.abort("state-machine abort")
        assert len(transport) <= transport.capacity


def run(seed_count: int) -> dict[str, int]:
    session_count = 0
    for seed in range(seed_count):
        rng = random.Random(seed)
        exercise_transport(rng)
        with tempfile.TemporaryDirectory(prefix="rpi-vstim-state-") as temporary:
            config = config_from_mapping({"paths": {"output_root": Path(temporary)}})
            result = run_simulated_session(
                config,
                session_id=f"session-{seed}",
                seed=seed,
                interrupt=rng.choice((False, True)),
                camera_failures=(),
            )
            assert result.final_state.value in {"COMPLETE", "INTERRUPTED"}
            session_count += 1
    return {"seeds": seed_count, "sessions": session_count}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=1000)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    print(json.dumps(run(args.seeds), sort_keys=True))


if __name__ == "__main__":
    main()
