from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import pairwise

from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets

DIRECTIONS = {
    "left_to_right": (0, "azimuth", "left", "right", "x"),
    "right_to_left": (1, "azimuth", "right", "left", "x"),
    "top_to_bottom": (2, "elevation", "top", "bottom", "y"),
    "bottom_to_top": (3, "elevation", "bottom", "top", "y"),
}


@dataclass(frozen=True)
class RetinotopySettings:
    sweep_duration_s: float = 20.0
    inter_sweep_gray_s: float = 5.0
    initial_gray_s: float = 3.0
    final_gray_s: float = 3.0
    movement_frame_rate_hz: int = 15
    bar_width_fraction: float = 0.10
    enabled_directions: tuple[str, ...] = ("left_to_right", "top_to_bottom")
    repeats_per_direction: int = 20
    sequence_order_mode: str = "fixed"
    refresh_hz: float = 60.0
    sequence_seed: int = 0

    def __post_init__(self) -> None:
        numeric_values = (
            self.sweep_duration_s,
            self.inter_sweep_gray_s,
            self.initial_gray_s,
            self.final_gray_s,
            self.bar_width_fraction,
            self.refresh_hz,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError("retinotopy settings must be finite numbers")
        if min(self.sweep_duration_s, self.inter_sweep_gray_s, self.initial_gray_s, self.final_gray_s) <= 0:
            raise ValueError("all durations must be positive")
        if self.refresh_hz <= 0 or type(self.movement_frame_rate_hz) is not int or self.movement_frame_rate_hz <= 0:
            raise ValueError("frame rates must be positive")
        if self.refresh_hz < self.movement_frame_rate_hz:
            raise ValueError("refresh_hz must be at least movement_frame_rate_hz")
        if not 0 < self.bar_width_fraction < 0.5:
            raise ValueError("bar_width_fraction must be between 0 and 0.5")
        directions = tuple(self.enabled_directions)
        if not directions or len(set(directions)) != len(directions):
            raise ValueError("enabled_directions must be unique and non-empty")
        if any(direction not in DIRECTIONS for direction in directions):
            raise ValueError("unknown retinotopy direction")
        object.__setattr__(self, "enabled_directions", directions)
        if type(self.repeats_per_direction) is not int or self.repeats_per_direction < 1:
            raise ValueError("repeats_per_direction must be positive")
        if self.sequence_order_mode not in {"fixed", "shuffled"}:
            raise ValueError("sequence_order_mode must be fixed or shuffled")
        if type(self.sequence_seed) is not int:
            raise ValueError("sequence_seed must be an integer")


def build_plan(settings: RetinotopySettings) -> SessionPlan:
    sweep_source_frames = round(settings.sweep_duration_s * settings.movement_frame_rate_hz)
    if sweep_source_frames < 1:
        raise ValueError("sweep_duration_s must produce at least one movement frame")
    refresh_counts = refreshes_per_source_frame(
        sweep_source_frames, settings.refresh_hz, settings.movement_frame_rate_hz
    )
    sweep_frames = sum(refresh_counts)
    rng = random.Random(settings.sequence_seed)
    directions: list[str] = []
    for _ in range(settings.repeats_per_direction):
        cycle = list(settings.enabled_directions)
        if settings.sequence_order_mode == "shuffled":
            rng.shuffle(cycle)
        directions.extend(cycle)
    events: list[PlannedEvent] = [
        PlannedEvent(
            "initial-gray",
            "gray",
            round(settings.initial_gray_s * settings.refresh_hz),
            phase="PRE",
        )
    ]
    for index, direction in enumerate(directions, start=1):
        code, axis, start_edge, end_edge, movement_axis = DIRECTIONS[direction]
        events.append(
            PlannedEvent(
                f"sweep-{index}",
                "retinotopy-sweep",
                sweep_frames,
                trial_id=str(index),
                sequence_id=direction,
                photodiode="on",
                metadata={
                    "direction": direction,
                    "direction_code": code,
                    "axis": axis,
                    "start_edge": start_edge,
                    "end_edge": end_edge,
                    "movement_axis": movement_axis,
                    "repeat_number": (index - 1) // len(settings.enabled_directions) + 1,
                    "bar_width_fraction": settings.bar_width_fraction,
                },
            )
        )
        events.append(
            PlannedEvent(
                f"inter-sweep-gray-{index}",
                "gray",
                round(settings.inter_sweep_gray_s * settings.refresh_hz),
                trial_id=str(index),
                photodiode="off",
            )
        )
    events.append(
        PlannedEvent(
            "final-gray",
            "gray",
            round(settings.final_gray_s * settings.refresh_hz),
            phase="POST",
        )
    )
    return SessionPlan(
        "retinotopy",
        settings.sequence_seed,
        with_frame_offsets(events),
        metadata={"enabled_directions": list(settings.enabled_directions)},
    )


def refreshes_per_source_frame(
    source_frame_count: int,
    refresh_hz: float,
    movement_frame_rate_hz: float,
) -> tuple[int, ...]:
    """Distribute nominal refreshes by cumulative rounded frame boundaries."""
    if source_frame_count < 1 or refresh_hz <= 0 or movement_frame_rate_hz <= 0:
        raise ValueError("frame counts and rates must be positive")
    if refresh_hz < movement_frame_rate_hz:
        raise ValueError("display refresh rate must not be below movement rate")
    ratio = refresh_hz / movement_frame_rate_hz
    boundaries = [round(index * ratio) for index in range(source_frame_count + 1)]
    counts = tuple(right - left for left, right in pairwise(boundaries))
    if any(count < 1 for count in counts):
        raise ValueError("movement rate produces a source frame with no display refresh")
    return counts


class RetinotopyProtocol:
    name = "retinotopy"
    version = "unified-0.1"

    def build_plan(self, settings: RetinotopySettings) -> SessionPlan:
        return build_plan(settings)


protocol = RetinotopyProtocol()
