from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectionDefinition:
    direction: str
    direction_code: int
    axis: str
    start_edge: str
    end_edge: str
    movement_axis: str
    sign: int


DIRECTION_DEFINITIONS = {
    "left_to_right": DirectionDefinition("left_to_right", 0, "azimuth", "left", "right", "x", 1),
    "right_to_left": DirectionDefinition("right_to_left", 1, "azimuth", "right", "left", "x", -1),
    "top_to_bottom": DirectionDefinition("top_to_bottom", 2, "elevation", "top", "bottom", "y", 1),
    "bottom_to_top": DirectionDefinition("bottom_to_top", 3, "elevation", "bottom", "top", "y", -1),
}


def get_direction(direction: str) -> DirectionDefinition:
    try:
        return DIRECTION_DEFINITIONS[direction]
    except KeyError as exc:
        raise ValueError(f"unknown retinotopy direction: {direction}") from exc
