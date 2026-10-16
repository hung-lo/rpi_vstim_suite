#!/usr/bin/env python3
"""Validate classified GPIO26/27 licks while retaining raw edges separately."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rpi_vstim.core.config import ConfigError, load_config
from rpi_vstim.hardware.lgpio_lick import (
    ClassifiedLick,
    LgpioLickMonitor,
    LickEventRecorder,
    RawLickEdge,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/rpi-vstim-lick-validation"))
    parser.add_argument("--idle-seconds", type=float, default=5.0)
    parser.add_argument("--left-seconds", type=float, default=25.0)
    parser.add_argument("--pause-seconds", type=float, default=3.0)
    parser.add_argument("--right-seconds", type=float, default=25.0)
    parser.add_argument("--final-seconds", type=float, default=3.0)
    parser.add_argument("--channel", choices=("both", "left", "right"), default="both")
    parser.add_argument("--expected-licks", type=int, default=20)
    parser.add_argument("--integrated", action="store_true")
    parser.add_argument("--integrated-seconds", type=float, default=10.0)
    parser.add_argument("--display-binary", type=Path, default=Path("native/kms_display/kms_probe"))
    parser.add_argument("--display-frames", type=int, default=600)
    return parser


def _write_edge(handle, edge: RawLickEdge | ClassifiedLick) -> None:
    handle.write(json.dumps(asdict(edge), sort_keys=True) + "\n")
    handle.flush()


def _phase_counts(items: list[RawLickEdge | ClassifiedLick], phases: dict[str, tuple[int, int]]) -> dict[str, dict[str, int]]:
    result = {name: {"lick_left": 0, "lick_right": 0} for name in phases}
    for item in items:
        for name, (start_ns, end_ns) in phases.items():
            if start_ns <= item.timestamp_ns < end_ns:
                result[name][item.channel] += 1
                break
    return result


def _camera_process(index: int, output: Path, duration_ms: int) -> subprocess.Popen[Any]:
    command = (
        "rpicam-vid",
        "--camera",
        str(index),
        "--width",
        "640",
        "--height",
        "480",
        "--framerate",
        "30",
        "--no-raw",
        "--nopreview",
        "--codec",
        "h264",
        "--bitrate",
        "1000000",
        "--inline",
        "--timeout",
        str(duration_ms),
        "--output",
        str(output),
    )
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _stop_process(process: subprocess.Popen[Any], *, stop_signal: signal.Signals = signal.SIGTERM) -> int | None:
    if process.poll() is None:
        process.send_signal(stop_signal)
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def _finish_process(process: subprocess.Popen[Any], timeout: float = 5) -> int | None:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _stop_process(process)


def _run_integrated(config_path: Path, args: argparse.Namespace, monitor: LgpioLickMonitor, root: Path) -> dict[str, object]:
    duration_s = args.integrated_seconds
    if duration_s <= 0 or args.display_frames < 1:
        raise ValueError("integrated duration and display frames must be positive")
    root.mkdir(parents=True, exist_ok=True)
    camera_outputs = [root / "camera_0.h264", root / "camera_1.h264"]
    camera_logs = [root / "camera_0.stderr", root / "camera_1.stderr"]
    display_log = root / "display.json"
    processes: list[subprocess.Popen[Any]] = []
    camera_processes: list[subprocess.Popen[Any]] = []
    display_process: subprocess.Popen[Any] | None = None
    monitor.start()
    try:
        for index, output in enumerate(camera_outputs):
            process = _camera_process(index, output, round((duration_s + 2) * 1000))
            processes.append(process)
            camera_processes.append(process)
        display_command = (
            sys.executable,
            "-m",
            "rpi_vstim",
            "hardware",
            "kms-render-smoke",
            "--config",
            str(config_path),
            "--binary",
            str(args.display_binary),
            "--frames",
            str(args.display_frames),
            "--lease",
            "--json",
        )
        with display_log.open("w") as handle:
            display_process = subprocess.Popen(
                display_command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            processes.append(display_process)
            print("INTEGRATED: perform a few LEFT contacts, then a few RIGHT contacts now", flush=True)
            time.sleep(duration_s)
        camera_statuses = [
            _stop_process(process, stop_signal=signal.SIGINT) for process in camera_processes
        ]
        display_status = _finish_process(display_process) if display_process is not None else None
    finally:
        for process in processes:
            if process.poll() is None:
                _stop_process(process)
        monitor.stop()
    for index, log in enumerate(camera_logs):
        if index < len(processes) and processes[index].stderr is not None:
            log.write_bytes(processes[index].stderr.read() or b"")
    return {
        "mode": "integrated",
        "duration_s": duration_s,
        "camera_exit_statuses": camera_statuses,
        "display_exit_status": display_status,
        "camera_output_bytes": [path.stat().st_size if path.exists() else 0 for path in camera_outputs],
        "display_log": str(display_log),
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_config(args.config)
    if config.hardware.backend != "lgpio":
        raise ConfigError("lick validation requires hardware.backend=lgpio")
    durations = (
        args.idle_seconds,
        args.left_seconds,
        args.pause_seconds,
        args.right_seconds,
        args.final_seconds,
    )
    if any(value <= 0 for value in durations):
        raise ValueError("validation durations must be positive")
    if args.expected_licks < 0:
        raise ValueError("expected lick count must not be negative")
    args.output_root.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_root / "raw_edges.jsonl"
    classified_path = args.output_root / "classified_licks.jsonl"
    result_path = args.output_root / "summary.json"
    recorder = LickEventRecorder()
    phases: dict[str, tuple[int, int]] = {}
    with raw_path.open("w") as raw_file, classified_path.open("w") as classified_file:
        def record_raw(edge: RawLickEdge) -> None:
            recorder.record_raw(edge)
            _write_edge(raw_file, edge)

        def record_classified(lick: ClassifiedLick) -> None:
            recorder.record_classified(lick)
            _write_edge(classified_file, lick)

        monitor = LgpioLickMonitor(
            config.hardware,
            on_raw_edge=record_raw,
            on_classified=record_classified,
        )
        integrated: dict[str, object] = {}
        if args.integrated:
            integrated = _run_integrated(args.config, args, monitor, args.output_root)
        else:
            monitor.start()
            try:
                phases["idle"] = (time.monotonic_ns(), 0)
                print("IDLE: baseline", flush=True)
                time.sleep(args.idle_seconds)
                phases["idle"] = (phases["idle"][0], time.monotonic_ns())
                if args.channel in {"both", "left"}:
                    phases["left"] = (time.monotonic_ns(), 0)
                    print(f"LEFT: perform exactly {args.expected_licks} contacts now", flush=True)
                    time.sleep(args.left_seconds)
                    phases["left"] = (phases["left"][0], time.monotonic_ns())
                if args.channel == "both":
                    phases["pause"] = (time.monotonic_ns(), 0)
                    print("PAUSE: stop contacts", flush=True)
                    time.sleep(args.pause_seconds)
                    phases["pause"] = (phases["pause"][0], time.monotonic_ns())
                if args.channel in {"both", "right"}:
                    phases["right"] = (time.monotonic_ns(), 0)
                    print(f"RIGHT: perform exactly {args.expected_licks} contacts now", flush=True)
                    time.sleep(args.right_seconds)
                    phases["right"] = (phases["right"][0], time.monotonic_ns())
                phases["final"] = (time.monotonic_ns(), 0)
                print("FINAL: release and remain idle", flush=True)
                time.sleep(args.final_seconds)
                phases["final"] = (phases["final"][0], time.monotonic_ns())
            finally:
                monitor.stop()
        raw_by_channel = dict(monitor.raw_edge_count)
        classified_by_channel = dict(monitor.classified_count)
        result = {
            "mode": "physical" if not args.integrated else "integrated",
            "channel_mode": args.channel,
            "pins": {"lick_left": config.hardware.lick_pin_bcm, "lick_right": config.hardware.lick_right_pin_bcm},
            "idle_level": config.hardware.lick_idle_level,
            "active_level": config.hardware.lick_active_level,
            "release_stable_ms": config.hardware.release_stable_ms,
            "min_classified_lick_interval_ms": config.hardware.min_classified_lick_interval_ms,
            "expected_licks_per_selected_channel": args.expected_licks,
            "raw_edge_count": raw_by_channel,
            "classified_lick_count": classified_by_channel,
            "raw_edge_count_total": len(recorder.raw_edges),
            "classified_lick_count_total": len(recorder.classified_licks),
            "raw_edges_by_phase": _phase_counts(recorder.raw_edges, phases) if phases else {},
            "classified_by_phase": _phase_counts(recorder.classified_licks, phases) if phases else {},
            "final_level": dict(monitor.last_level),
            "cross_talk_raw_edges": {
                "during_left": sum(
                    item.channel == "lick_right"
                    for item in recorder.raw_edges
                    if phases.get("left", (0, 0))[0] <= item.timestamp_ns < phases.get("left", (0, 0))[1]
                ),
                "during_right": sum(
                    item.channel == "lick_left"
                    for item in recorder.raw_edges
                    if phases.get("right", (0, 0))[0] <= item.timestamp_ns < phases.get("right", (0, 0))[1]
                ),
            },
            "callback_errors": list(monitor.callback_errors),
            "released": not monitor.started,
            **integrated,
        }
        if not args.integrated:
            expected = {
                "lick_left": args.expected_licks if args.channel in {"both", "left"} else 0,
                "lick_right": args.expected_licks if args.channel in {"both", "right"} else 0,
            }
            result["accepted"] = (
                classified_by_channel == expected
                and all(value == config.hardware.lick_idle_level for value in monitor.last_level.values())
                and all(value == 0 for value in result["cross_talk_raw_edges"].values())
                and len(recorder.raw_edges) > len(recorder.classified_licks)
                and not monitor.callback_errors
            )
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    try:
        result = run(_parser().parse_args())
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    result["ok"] = True
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
