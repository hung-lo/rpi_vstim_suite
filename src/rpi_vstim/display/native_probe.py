"""Bounded wrapper for the standalone native DRM/KMS probe."""

from __future__ import annotations

import json
import os
import signal
import struct
import subprocess
from collections.abc import Iterable
from pathlib import Path
from queue import Full, Queue
from threading import Event, Thread
from typing import Any

from rpi_vstim.core.config import DisplayConfig

from .models import DisplayResult
from .transport import DisplaySequenceFrame

_STREAM_MAGIC = b"RPIKMS1\0"
_STREAM_VERSION = 1
_STREAM_HEADER = struct.Struct("<8sII")
_STREAM_FRAME_HEADER = struct.Struct("<QQBQ7x")
# 32 packed frames cover bounded image preparation latency at 60 Hz without
# retaining an unbounded experiment session in memory.
_STREAM_QUEUE_CAPACITY = 32


class NativeKmsError(RuntimeError):
    """Raised when the native probe cannot complete safely."""


class NativeKmsOwnershipError(NativeKmsError):
    """Raised when another compositor/session owns DRM modesetting authority."""


def default_binary() -> Path:
    override = os.environ.get("RPI_VSTIM_KMS_PROBE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "native" / "kms_display" / "kms_probe"


def _lease_environment() -> dict[str, str]:
    """Supply the local Wayland runtime to a leased child launched over SSH."""
    environment = dict(os.environ)
    if environment.get("XDG_RUNTIME_DIR"):
        return environment
    runtime_dir = Path("/run/user") / str(os.getuid())
    if runtime_dir.is_dir() and (runtime_dir / "wayland-0").is_socket():
        environment["XDG_RUNTIME_DIR"] = str(runtime_dir)
        environment.setdefault("WAYLAND_DISPLAY", "wayland-0")
    return environment


def run_native_probe(
    config: DisplayConfig,
    *,
    frames: int,
    binary: Path | str | None = None,
    device: str | None = None,
    color: tuple[int, int, int] | None = None,
    patch_size: int = 50,
    patch_corner: str = "bottom_right",
    patch_on: int = 255,
    patch_off: int = 0,
    probe_only: bool = False,
    lease: bool = False,
    frame_file: Path | str | None = None,
) -> dict[str, Any]:
    if frames <= 0:
        raise ValueError("frames must be positive")
    executable = Path(binary) if binary is not None else default_binary()
    command = [
        str(executable),
        "--connector",
        config.stimulus_connector,
        "--width",
        str(config.width_px),
        "--height",
        str(config.height_px),
        "--refresh",
        f"{config.refresh_hz:g}",
        "--tolerance",
        f"{config.refresh_tolerance_hz if config.require_exact_refresh else 1000000:g}",
        "--format",
        config.pixel_format,
        "--frames",
        str(frames),
        "--patch-size",
        str(patch_size),
        "--patch-corner",
        patch_corner,
        "--patch-on",
        str(patch_on),
        "--patch-off",
        str(patch_off),
        "--json",
    ]
    if probe_only:
        command.append("--probe-only")
    if lease:
        command.append("--lease")
    if device:
        command.extend(("--device", device))
    if color is not None:
        if len(color) != 3 or any(not 0 <= value <= 255 for value in color):
            raise ValueError("color must contain three values from 0 to 255")
        command.extend(("--color", ",".join(str(value) for value in color)))
    if frame_file is not None:
        command.extend(("--frame-file", str(frame_file)))
    timeout = max(10.0, frames / max(config.refresh_hz, 1.0) + 5.0)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            **({"env": _lease_environment()} if lease else {}),
        )
    except FileNotFoundError as exc:
        raise NativeKmsError(f"native KMS probe is unavailable: {executable}") from exc
    except subprocess.TimeoutExpired as exc:
        raise NativeKmsError(f"native KMS probe timed out after {timeout:.1f}s") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        message = f"native KMS probe failed ({result.returncode}): {detail}"
        lowered = detail.lower()
        if "modesetting authority" in lowered or "drm master" in lowered:
            raise NativeKmsOwnershipError(message)
        raise NativeKmsError(message)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise NativeKmsError("native KMS probe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise NativeKmsError("native KMS probe returned a non-object result")
    return payload


def run_native_sequence(
    config: DisplayConfig,
    frames: Iterable[DisplaySequenceFrame],
    *,
    binary: Path | str | None = None,
    patch_size: int = 50,
    patch_corner: str = "bottom_right",
    patch_on: int = 255,
    patch_off: int = 0,
    lease: bool = False,
) -> dict[str, Any]:
    """Run one continuous leased KMS session for a bounded frame stream."""
    if patch_size <= 0 or not 0 <= patch_on <= 255 or not 0 <= patch_off <= 255:
        raise ValueError("invalid photodiode configuration")
    bytes_per_pixel = {"RGB565": 2, "XRGB8888": 4}.get(config.pixel_format)
    if bytes_per_pixel is None:
        raise ValueError(f"unsupported pixel format: {config.pixel_format}")
    frame_bytes = config.width_px * config.height_px * bytes_per_pixel
    executable = Path(binary) if binary is not None else default_binary()
    command = [
        str(executable),
        "--connector",
        config.stimulus_connector,
        "--width",
        str(config.width_px),
        "--height",
        str(config.height_px),
        "--refresh",
        f"{config.refresh_hz:g}",
        "--tolerance",
        f"{config.refresh_tolerance_hz if config.require_exact_refresh else 1000000:g}",
        "--format",
        config.pixel_format,
        "--patch-size",
        str(patch_size),
        "--patch-corner",
        patch_corner,
        "--patch-on",
        str(patch_on),
        "--patch-off",
        str(patch_off),
        "--stream",
        "--json",
    ]
    if lease:
        command.append("--lease")

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        **({"env": _lease_environment()} if lease else {}),
    )
    frame_queue: Queue[DisplaySequenceFrame | None] = Queue(maxsize=_STREAM_QUEUE_CAPACITY)
    stop_producer = Event()
    producer_error: list[BaseException] = []
    writer_error: list[BaseException] = []
    frame_count = 0
    producer_sequence = 0

    def produce_frames() -> None:
        try:
            for frame in frames:
                while not stop_producer.is_set():
                    try:
                        frame_queue.put(frame, timeout=0.1)
                        break
                    except Full:
                        continue
                if stop_producer.is_set():
                    return
        except BaseException as exc:  # noqa: BLE001 — propagate producer cancellation safely
            producer_error.append(exc)
        finally:
            while not stop_producer.is_set():
                try:
                    frame_queue.put(None, timeout=0.1)
                    return  # noqa: B012 — sentinel enqueue completed
                except Full:
                    continue

    def write_frames() -> None:
        nonlocal frame_count, producer_sequence
        assert process.stdin is not None
        try:
            process.stdin.write(_STREAM_HEADER.pack(_STREAM_MAGIC, _STREAM_VERSION, frame_bytes))
            while True:
                frame = frame_queue.get()
                if frame is None:
                    if producer_error:
                        raise NativeKmsError(
                            f"display sequence producer failed: {producer_error[0]}"
                        )
                    break
                metadata = frame.metadata
                payload = bytes(frame.payload)
                if metadata.logical_frame_index != frame_count:
                    raise ValueError("display sequence frame indices are not contiguous")
                if metadata.producer_sequence != producer_sequence:
                    raise ValueError("display sequence producer sequence is not contiguous")
                if metadata.payload_size != len(payload) or len(payload) != frame_bytes:
                    raise ValueError("display sequence payload size does not match display")
                if metadata.photodiode_state not in {"on", "off"}:
                    raise ValueError("display sequence photodiode state is invalid")
                process.stdin.write(
                    _STREAM_FRAME_HEADER.pack(
                        metadata.logical_frame_index,
                        metadata.producer_sequence,
                        1 if metadata.photodiode_state == "on" else 0,
                        len(payload),
                    )
                )
                process.stdin.write(payload)
                frame_count += 1
                producer_sequence += 1
        except BaseException as exc:  # noqa: BLE001 — fail-safe native cleanup
            writer_error.append(exc)
            stop_producer.set()
            if process.poll() is None:
                process.kill()
        finally:
            process.stdin.close()

    producer = Thread(target=produce_frames, name="rpi-vstim-kms-stream-producer")
    writer = Thread(target=write_frames, name="rpi-vstim-kms-stream-writer")
    try:
        producer.start()
        writer.start()
        writer.join()
    except BaseException:
        # Ctrl-C/SIGTERM must not leave the native KMS owner or its producer
        # threads behind.  The native process also restores the original CRTC
        # during its normal signal-aware cleanup when it can do so.
        stop_producer.set()
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
        producer.join(timeout=2.0)
        writer.join(timeout=2.0)
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        raise
    stop_producer.set()
    producer.join()
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.wait()
    if writer_error:
        detail = stderr.decode(errors="replace").strip()
        message = f"native KMS sequence input failed: {writer_error[0]}"
        raise NativeKmsError(f"{message}: {detail}" if detail else message)
    if process.returncode != 0:
        detail = (stderr or stdout).decode(errors="replace").strip()
        message = f"native KMS sequence failed ({process.returncode}): {detail}"
        lowered = detail.lower()
        if "modesetting authority" in lowered or "drm master" in lowered:
            raise NativeKmsOwnershipError(message)
        raise NativeKmsError(message)
    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        raise NativeKmsError("native KMS sequence returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise NativeKmsError("native KMS sequence returned a non-object result")
    if int(payload.get("completed_frame_count", -1)) != frame_count:
        raise NativeKmsError("native KMS sequence completed a different frame count")
    payload["producer_frame_count"] = frame_count
    return payload


def display_result_from_probe(
    payload: dict[str, Any],
    config: DisplayConfig,
    *,
    sequence_id: str,
) -> DisplayResult:
    required = (
        "connector",
        "selected_mode",
        "pixel_format",
        "requested_frame_count",
        "completed_frame_count",
    )
    missing = [name for name in required if name not in payload]
    if missing:
        raise NativeKmsError(f"native KMS result is missing fields: {', '.join(missing)}")
    if payload["connector"] != config.stimulus_connector:
        raise NativeKmsError("native KMS result selected an unexpected connector")
    if payload["pixel_format"] != config.pixel_format:
        raise NativeKmsError("native KMS result selected an unexpected pixel format")
    return DisplayResult(
        backend_name="kms",
        connector=str(payload["connector"]),
        mode=str(payload["selected_mode"]),
        pixel_format=str(payload["pixel_format"]),
        sequence_id=sequence_id,
        requested_frame_count=int(payload["requested_frame_count"]),
        completed_frame_count=int(payload["completed_frame_count"]),
        first_page_flip_kernel_event_ns=_optional_int(payload, "first_page_flip_kernel_event_ns"),
        last_page_flip_kernel_event_ns=_optional_int(payload, "last_page_flip_kernel_event_ns"),
        first_page_flip_callback_monotonic_ns=_timestamp(
            payload,
            "first_page_flip_callback_monotonic_ns",
            "first_page_flip_monotonic_ns",
        ),
        last_page_flip_callback_monotonic_ns=_timestamp(
            payload,
            "last_page_flip_callback_monotonic_ns",
            "last_page_flip_monotonic_ns",
        ),
        first_page_flip_callback_realtime_ns=_timestamp(
            payload,
            "first_page_flip_callback_realtime_ns",
            "first_page_flip_realtime_ns",
        ),
        last_page_flip_callback_realtime_ns=_optional_int(
            payload, "last_page_flip_callback_realtime_ns"
        ),
        timing_source=str(
            payload.get("timing_source", "legacy_callback_monotonic")
        ),
        kernel_timestamp_clock=str(payload.get("kernel_timestamp_clock", "unknown")),
        mean_vblank_interval_us=float(payload["mean_vblank_interval_us"]),
        std_vblank_interval_us=float(payload["std_vblank_interval_us"]),
        maximum_vblank_interval_us=float(payload["maximum_vblank_interval_us"]),
        missed_vblank_count=int(payload["missed_vblank_count"]),
        aborted=bool(payload["aborted"]),
        error=None,
        p95_vblank_interval_us=_optional_float(payload, "p95_vblank_interval_us"),
        p99_vblank_interval_us=_optional_float(payload, "p99_vblank_interval_us"),
        intervals_outside_tolerance=int(payload.get("intervals_outside_tolerance", 0)),
        estimated_dropped_frame_count=int(payload.get("estimated_dropped_frame_count", 0)),
        photodiode_state=_photodiode_state(payload),
    )


def _optional_float(payload: dict[str, Any], name: str) -> float | None:
    value = payload.get(name)
    return None if value is None else float(value)


def _optional_int(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    return None if value is None else int(value)


def _timestamp(payload: dict[str, Any], current: str, legacy: str) -> int | None:
    if current in payload:
        return _optional_int(payload, current)
    return _optional_int(payload, legacy)


def _photodiode_state(payload: dict[str, Any]) -> str | None:
    value = payload.get("photodiode")
    if not isinstance(value, dict):
        return None
    return str(value.get("frame_state")) if value.get("frame_state") is not None else None
