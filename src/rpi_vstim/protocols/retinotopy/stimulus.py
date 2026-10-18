from __future__ import annotations

import numpy as np

from rpi_vstim.core.config import Config

from . import RetinotopySettings
from .directions import get_direction


def bar_width_px(config: Config, settings: RetinotopySettings, direction: str) -> int:
    axis = get_direction(direction).movement_axis
    dimension = config.display.width_px if axis == "x" else config.display.height_px
    return max(1, round(dimension * settings.bar_width_fraction))


def boundary_positions_px(config: Config, settings: RetinotopySettings, direction: str) -> np.ndarray:
    definition = get_direction(direction)
    axis = definition.movement_axis
    dimension = config.display.width_px if axis == "x" else config.display.height_px
    width = bar_width_px(config, settings, direction)
    positions = np.linspace(-width, dimension + width, round(
        settings.sweep_duration_s * settings.movement_frame_rate_hz
    ))
    if definition.sign < 0:
        positions = positions[::-1]
    return positions


def generate_retinotopy_frame(
    config: Config,
    settings: RetinotopySettings,
    *,
    direction: str,
    source_frame_index: int,
) -> np.ndarray:
    positions = boundary_positions_px(config, settings, direction)
    if not 0 <= source_frame_index < len(positions):
        raise IndexError("retinotopy source frame index is out of range")
    boundary = round(float(positions[source_frame_index]))
    width = bar_width_px(config, settings, direction)
    frame = np.full(
        (config.display.height_px, config.display.width_px, 3), 127, dtype=np.uint8
    )

    def clipped(start: int, end: int, dimension: int) -> tuple[int, int]:
        return max(0, min(dimension, start)), max(0, min(dimension, end))

    if get_direction(direction).movement_axis == "x":
        black_start, black_end = clipped(boundary - width, boundary, config.display.width_px)
        white_start, white_end = clipped(boundary, boundary + width, config.display.width_px)
        if black_start < black_end:
            frame[:, black_start:black_end, :] = 0
        if white_start < white_end:
            frame[:, white_start:white_end, :] = 255
    else:
        black_start, black_end = clipped(boundary - width, boundary, config.display.height_px)
        white_start, white_end = clipped(boundary, boundary + width, config.display.height_px)
        if black_start < black_end:
            frame[black_start:black_end, :, :] = 0
        if white_start < white_end:
            frame[white_start:white_end, :, :] = 255
    return frame
