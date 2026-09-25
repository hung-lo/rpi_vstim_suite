"""Bounded wrapper for the standalone native DRM/KMS probe."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from rpi_vstim.core.config import DisplayConfig

from .models import DisplayResult


class NativeKmsError(RuntimeError):
    """Raised when the native probe cannot complete safely."""


class NativeKmsOwnershipError(NativeKmsError):
    """Raised when another compositor/session owns DRM modesetting authority."""


def default_binary() -> Path:
    override = os.environ.get("RPI_VSTIM_KMS_PROBE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "native" / "kms_display" / "kms_probe"


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
        first_page_flip_monotonic_ns=int(payload["first_page_flip_monotonic_ns"]),
        last_page_flip_monotonic_ns=int(payload["last_page_flip_monotonic_ns"]),
        first_page_flip_realtime_ns=int(payload["first_page_flip_realtime_ns"]),
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


def _photodiode_state(payload: dict[str, Any]) -> str | None:
    value = payload.get("photodiode")
    if not isinstance(value, dict):
        return None
    return str(value.get("frame_state")) if value.get("frame_state") is not None else None
