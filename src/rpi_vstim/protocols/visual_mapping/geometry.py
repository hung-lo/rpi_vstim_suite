from __future__ import annotations

import math
from typing import Any

from rpi_vstim.core.config import Config


def geometry_snapshot(config: Config) -> dict[str, Any]:
    display = config.display
    return {
        "screen_width_px": display.width_px,
        "screen_height_px": display.height_px,
        "active_width_cm": display.physical_width_cm,
        "active_height_cm": display.physical_height_cm,
        "eye_screen_distance_cm": display.eye_distance_cm,
        "screen_center_px": {
            "x": (display.width_px - 1) / 2.0,
            "y": (display.height_px - 1) / 2.0,
        },
        "screen_coordinate_convention": "origin at pixel-grid center; +x right; +y up",
        "visual_angle_model": "atan2(screen_plane_cm, eye_screen_distance_cm), planar unwarped screen",
        "refresh_hz": display.refresh_hz,
        "pixel_format": display.pixel_format,
        "calibration_id": display.calibration_id,
    }


def pixel_to_screen_cm(config: Config, x_px: float, y_px: float) -> tuple[float, float]:
    display = config.display
    x_cm = (x_px - (display.width_px - 1) / 2.0) * display.physical_width_cm / display.width_px
    y_cm = ((display.height_px - 1) / 2.0 - y_px) * display.physical_height_cm / display.height_px
    return x_cm, y_cm


def screen_cm_to_visual_angle_deg(config: Config, x_cm: float, y_cm: float) -> tuple[float, float]:
    distance = config.display.eye_distance_cm
    return math.degrees(math.atan2(x_cm, distance)), math.degrees(math.atan2(y_cm, distance))
