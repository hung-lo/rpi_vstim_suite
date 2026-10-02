#!/usr/bin/env python3
"""Validate one configured Pi GPIO output line without touching any other pin."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from rpi_vstim.core.config import ConfigError, load_config
from rpi_vstim.hardware.lgpio_backend import LgpioBackend, LgpioUnavailableError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--role", choices=("reward", "vacuum"), required=True)
    parser.add_argument(
        "--test", choices=("line", "pulse", "startup", "exception", "hold"), default="line"
    )
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--pulse-ms", type=float, default=50.0)
    parser.add_argument("--hold-s", type=float, default=5.0)
    return parser


def _transition_event(transition) -> dict[str, object]:
    return asdict(transition)


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_config(args.config)
    if config.hardware.backend != "lgpio":
        raise ConfigError("GPIO validation requires hardware.backend=lgpio")
    if args.cycles < 1 or args.pulse_ms <= 0 or args.hold_s <= 0:
        raise ValueError("cycles and durations must be positive")
    line = config.hardware.output_line(args.role)
    result: dict[str, object] = {
        "test": args.test,
        "role": line.role,
        "chip": line.chip,
        "bcm_pin": line.bcm_pin,
        "initial_electrical_level": line.initial_level,
        "active_electrical_level": line.active_level,
        "events": [],
        "warnings": [],
        "release_success": False,
        "interrupted": False,
    }
    events = result["events"]
    assert isinstance(events, list)
    backend = LgpioBackend(config.hardware, roles=(line.role,))
    try:
        try:
            status = backend.start()
            events.append({"event": "acquired", "monotonic_ns": time.monotonic_ns(), "status": asdict(status)})
            if args.test == "line":
                time.sleep(1.0)
                for cycle in range(1, args.cycles + 1):
                    events.append({"cycle": cycle, "state": "HIGH", "transition": _transition_event(backend.set_level(line.role, 1))})
                    time.sleep(1.0)
                    events.append({"cycle": cycle, "state": "LOW", "transition": _transition_event(backend.set_level(line.role, 0))})
                    time.sleep(1.0)
            elif args.test == "pulse":
                backend.set_level(line.role, 0)
                events.append({"direction": "LOW_TO_HIGH", "pulse": asdict(backend.pulse(line.role, 1, args.pulse_ms / 1000.0, baseline_level=0))})
                backend.set_level(line.role, 1)
                events.append({"direction": "HIGH_TO_LOW", "pulse": asdict(backend.pulse(line.role, 0, args.pulse_ms / 1000.0, baseline_level=1))})
                backend.set_level(line.role, line.initial_level)
            elif args.test == "hold":
                time.sleep(args.hold_s)
            elif args.test == "exception":
                try:
                    raise RuntimeError("intentional GPIO ownership exception")
                except RuntimeError as exc:
                    events.append({"event": "intentional_exception", "message": str(exc)})
                    result["exception_handled"] = True
            events.append({"event": "final_readback", "level": backend.read_level(line.role), "monotonic_ns": time.monotonic_ns()})
        except KeyboardInterrupt:
            result["interrupted"] = True
        result["transitions"] = [_transition_event(item) for item in backend.transitions]
        result["warnings"] = list(backend.warnings)
    finally:
        try:
            backend.stop()
        finally:
            result["release_success"] = not backend.started
            result["released_monotonic_ns"] = time.monotonic_ns()
    return result


def main() -> int:
    try:
        result = run(_parser().parse_args())
    except (ConfigError, LgpioUnavailableError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
