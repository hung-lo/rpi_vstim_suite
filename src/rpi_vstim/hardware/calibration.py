"""Auditable single-continuous-open reward calibration profiles."""

from __future__ import annotations

import csv
import json
import math
import struct
import subprocess
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from .reward import DELIVERY_MODE, REWARD_GPIO_BCM, REWARD_ROLE

SCHEMA_VERSION = 1


class CalibrationError(ValueError):
    """Raised for invalid or unsafe calibration data."""


def mass_to_mean_volume_ul(initial_mass_g: float, final_mass_g: float, count: int) -> float:
    if not all(math.isfinite(value) for value in (initial_mass_g, final_mass_g)):
        raise CalibrationError("calibration masses must be finite")
    if count <= 0:
        raise CalibrationError("delivery_count must be positive")
    collected_mass_g = final_mass_g - initial_mass_g
    if collected_mass_g < 0:
        raise CalibrationError("final mass cannot be below initial mass")
    return collected_mass_g * 1000.0 / count


@dataclass(frozen=True)
class CalibrationCondition:
    open_duration_ms: float
    delivery_count: int
    initial_mass_g: float
    final_mass_g: float
    collected_mass_g: float
    mean_volume_ul: float

    @classmethod
    def measured(
        cls,
        open_duration_ms: float,
        delivery_count: int,
        initial_mass_g: float,
        final_mass_g: float,
    ) -> CalibrationCondition:
        if not math.isfinite(open_duration_ms) or open_duration_ms <= 0:
            raise CalibrationError("open_duration_ms must be finite and positive")
        mean_volume_ul = mass_to_mean_volume_ul(initial_mass_g, final_mass_g, delivery_count)
        return cls(
            float(open_duration_ms),
            int(delivery_count),
            float(initial_mass_g),
            float(final_mass_g),
            float(final_mass_g - initial_mass_g),
            mean_volume_ul,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "open_duration_ms": self.open_duration_ms,
            "delivery_count": self.delivery_count,
            "initial_mass_g": self.initial_mass_g,
            "final_mass_g": self.final_mass_g,
            "collected_mass_g": self.collected_mass_g,
            "mean_volume_ul": self.mean_volume_ul,
        }


def _linear_fit(points: list[CalibrationCondition]) -> dict[str, float]:
    xs = [point.open_duration_ms for point in points]
    ys = [point.mean_volume_ul for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator if denominator else 0.0
    intercept = y_mean - slope * x_mean
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    return {
        "slope_ul_per_ms": slope,
        "intercept_ul": intercept,
        "rmse_ul": math.sqrt(sum(value * value for value in residuals) / len(residuals)),
        "max_abs_residual_ul": max(abs(value) for value in residuals),
    }


@dataclass(frozen=True)
class CalibrationProfile:
    schema_version: int
    calibration_id: str
    created_at: str
    rig_id: str
    output_role: str
    gpio_bcm: int
    delivery_mode: str
    fluid: str
    operator: str
    conditions: tuple[CalibrationCondition, ...]
    valid_duration_range_ms: tuple[float, float]
    valid_volume_range_ul: tuple[float, float]
    calibration_fit: dict[str, Any]
    selected_target_volume_ul: float | None = None
    resolved_duration_ms: float | None = None
    software_commit: str = "unknown"
    hardware_backend: str = "lgpio"

    @classmethod
    def create(
        cls,
        *,
        calibration_id: str,
        rig_id: str,
        conditions: Iterable[CalibrationCondition],
        fluid: str = "water",
        operator: str = "",
        created_at: str | None = None,
        software_commit: str = "unknown",
        hardware_backend: str = "lgpio",
        selected_target_volume_ul: float | None = None,
    ) -> CalibrationProfile:
        values = tuple(conditions)
        if not calibration_id or not rig_id or not values:
            raise CalibrationError("calibration_id, rig_id, and at least one condition are required")
        if any(condition.delivery_count <= 0 for condition in values):
            raise CalibrationError("delivery counts must be positive")
        durations = [condition.open_duration_ms for condition in values]
        volumes = [condition.mean_volume_ul for condition in values]
        if len(set(durations)) != len(durations):
            raise CalibrationError("calibration durations must be unique")
        if len(set(volumes)) != len(volumes):
            raise CalibrationError("calibration volumes must be unique for interpolation")
        if selected_target_volume_ul is not None:
            _check_volume_range(selected_target_volume_ul, min(volumes), max(volumes))
        return cls(
            SCHEMA_VERSION,
            calibration_id,
            created_at or datetime.now(UTC).isoformat(),
            rig_id,
            REWARD_ROLE,
            REWARD_GPIO_BCM,
            DELIVERY_MODE,
            fluid,
            operator,
            values,
            (min(durations), max(durations)),
            (min(volumes), max(volumes)),
            {
                "interpolation": {"method": "piecewise_linear", "x": "mean_volume_ul", "y": "open_duration_ms"},
                "linear_fit": _linear_fit(list(values)),
            },
            selected_target_volume_ul,
            None,
            software_commit,
            hardware_backend,
        )

    def resolve_duration_ms(self, target_volume_ul: float) -> float:
        _check_volume_range(target_volume_ul, *self.valid_volume_range_ul)
        points = sorted(self.conditions, key=lambda point: point.mean_volume_ul)
        if target_volume_ul == points[0].mean_volume_ul:
            return points[0].open_duration_ms
        for left, right in pairwise(points):
            if target_volume_ul <= right.mean_volume_ul:
                fraction = (target_volume_ul - left.mean_volume_ul) / (
                    right.mean_volume_ul - left.mean_volume_ul
                )
                return left.open_duration_ms + fraction * (
                    right.open_duration_ms - left.open_duration_ms
                )
        return points[-1].open_duration_ms

    def with_target(self, target_volume_ul: float) -> CalibrationProfile:
        return replace(
            self,
            selected_target_volume_ul=target_volume_ul,
            resolved_duration_ms=self.resolve_duration_ms(target_volume_ul),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "created_at": self.created_at,
            "rig_id": self.rig_id,
            "output_role": self.output_role,
            "gpio_bcm": self.gpio_bcm,
            "delivery_mode": self.delivery_mode,
            "fluid": self.fluid,
            "operator": self.operator,
            "conditions": [condition.as_dict() for condition in self.conditions],
            "valid_duration_range_ms": list(self.valid_duration_range_ms),
            "valid_volume_range_ul": list(self.valid_volume_range_ul),
            "calibration_fit": self.calibration_fit,
            "selected_target_volume_ul": self.selected_target_volume_ul,
            "resolved_duration_ms": self.resolved_duration_ms,
            "software_commit": self.software_commit,
            "hardware_backend": self.hardware_backend,
        }


def _check_volume_range(value: float, minimum: float, maximum: float) -> None:
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise CalibrationError(
            f"requested reward volume {value} uL is outside calibrated range {minimum}..{maximum} uL"
        )


def load_profile(path: Path | str) -> CalibrationProfile:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CalibrationError(f"cannot read calibration profile: {exc}") from exc
    if not isinstance(payload, dict):
        raise CalibrationError("calibration profile must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CalibrationError("unsupported reward calibration schema_version")
    try:
        conditions = tuple(CalibrationCondition(**row) for row in payload.get("conditions", ()))
    except (TypeError, ValueError) as exc:
        raise CalibrationError("calibration profile contains an invalid condition") from exc
    required = (
        "calibration_id", "created_at", "rig_id", "output_role", "gpio_bcm",
        "delivery_mode", "fluid", "valid_duration_range_ms", "valid_volume_range_ul",
        "calibration_fit", "software_commit", "hardware_backend",
    )
    missing = [name for name in required if name not in payload]
    if missing or not conditions:
        raise CalibrationError("calibration profile is missing required fields")
    try:
        profile = CalibrationProfile(
            schema_version=payload["schema_version"],
            calibration_id=payload["calibration_id"],
            created_at=payload["created_at"],
            rig_id=payload["rig_id"],
            output_role=payload["output_role"],
            gpio_bcm=payload["gpio_bcm"],
            delivery_mode=payload["delivery_mode"],
            fluid=payload["fluid"],
            operator=payload.get("operator", ""),
            conditions=conditions,
            valid_duration_range_ms=tuple(payload["valid_duration_range_ms"]),
            valid_volume_range_ul=tuple(payload["valid_volume_range_ul"]),
            calibration_fit=payload["calibration_fit"],
            selected_target_volume_ul=payload.get("selected_target_volume_ul"),
            resolved_duration_ms=payload.get("resolved_duration_ms"),
            software_commit=payload["software_commit"],
            hardware_backend=payload["hardware_backend"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationError("calibration profile contains invalid fields") from exc
    if len(profile.valid_duration_range_ms) != 2 or len(profile.valid_volume_range_ul) != 2:
        raise CalibrationError("calibration profile ranges must contain two values")
    if profile.valid_duration_range_ms[0] > profile.valid_duration_range_ms[1]:
        raise CalibrationError("calibration duration range is reversed")
    if profile.valid_volume_range_ul[0] > profile.valid_volume_range_ul[1]:
        raise CalibrationError("calibration volume range is reversed")
    return profile


def profile_sha256(path: Path | str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_profile(profile: CalibrationProfile, path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(profile.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(profile: CalibrationProfile, path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(profile.conditions[0].as_dict()))
        writer.writeheader()
        writer.writerows(condition.as_dict() for condition in profile.conditions)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def write_png_curve(profile: CalibrationProfile, path: Path | str) -> None:
    """Write a small dependency-free PNG of measured volume versus open time."""
    width, height = 640, 420
    pixels = bytearray([255] * (width * height * 3))
    points = [(condition.open_duration_ms, condition.mean_volume_ul) for condition in profile.conditions]
    x_min, x_max = profile.valid_duration_range_ms
    y_min, y_max = profile.valid_volume_range_ul

    def pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset:offset + 3] = bytes(color)

    def xy(x_value: float, y_value: float) -> tuple[int, int]:
        x = 60 + round((x_value - x_min) / (x_max - x_min or 1) * 550)
        y = 360 - round((y_value - y_min) / (y_max - y_min or 1) * 320)
        return x, y

    for x in range(60, 611):
        pixel(x, 360, (0, 0, 0))
    for y in range(40, 361):
        pixel(60, y, (0, 0, 0))
    ordered = sorted(points)
    for left, right in pairwise(ordered):
        x0, y0 = xy(*left)
        x1, y1 = xy(*right)
        for step in range(max(abs(x1 - x0), abs(y1 - y0)) + 1):
            fraction = step / max(abs(x1 - x0), abs(y1 - y0), 1)
            pixel(round(x0 + fraction * (x1 - x0)), round(y0 + fraction * (y1 - y0)), (30, 90, 180))
    for point in points:
        x, y = xy(*point)
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if dx * dx + dy * dy <= 16:
                    pixel(x + dx, y + dy, (180, 30, 30))
    rows = b"".join(b"\x00" + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(png)


def current_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
