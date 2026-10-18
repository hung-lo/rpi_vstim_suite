from __future__ import annotations

import math
import random
from dataclasses import dataclass

from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets

DEFAULT_ORIENTATIONS_DEG = (0.0, 22.5, 45.0, 67.5, 90.0, 112.5, 135.0, 157.5)


@dataclass(frozen=True)
class RectangularPatchGeometry:
    center_x_cm: float
    center_y_cm: float
    width_cm: float
    height_cm: float


def normalize_orientation_deg(value: float) -> float:
    return float(value) % 180.0


def drift_direction_deg(bar_orientation_deg: float) -> float:
    return (normalize_orientation_deg(bar_orientation_deg) - 90.0) % 360.0


@dataclass(frozen=True)
class DriftingGratingSettings:
    orientations_deg: tuple[float, ...] = DEFAULT_ORIENTATIONS_DEG
    trials_per_orientation: int = 80
    stim_duration_s: float = 0.5
    iti_base_s: float = 0.7
    iti_jitter_max_s: float = 0.5
    temporal_frequency_hz: float = 2.0
    spatial_frequency_cycles_per_cm: float = 0.2
    contrast: float = 1.0
    mean_luminance: float = 0.5
    starting_phase_deg: float = 0.0
    initial_gray_s: float = 3.0
    final_gray_s: float = 3.0
    refresh_hz: float = 60.0
    sequence_seed: int = 0
    grating_mode: str = "fullscreen"
    rectangular_patch_geometry: RectangularPatchGeometry | None = None

    def __post_init__(self) -> None:
        numeric_values = (
            self.stim_duration_s,
            self.iti_base_s,
            self.iti_jitter_max_s,
            self.temporal_frequency_hz,
            self.spatial_frequency_cycles_per_cm,
            self.contrast,
            self.mean_luminance,
            self.starting_phase_deg,
            self.initial_gray_s,
            self.final_gray_s,
            self.refresh_hz,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError("grating settings must be finite numbers")
        orientations = tuple(normalize_orientation_deg(value) for value in self.orientations_deg)
        if any(not math.isfinite(value) for value in orientations):
            raise ValueError("orientations must be finite")
        if not orientations or len(set(orientations)) != len(orientations):
            raise ValueError("orientations must be unique and non-empty")
        if type(self.trials_per_orientation) is not int or self.trials_per_orientation < 1:
            raise ValueError("trials_per_orientation must be positive")
        if self.refresh_hz <= 0 or self.stim_duration_s <= 0:
            raise ValueError("refresh_hz and stim_duration_s must be positive")
        if self.iti_base_s < 0 or self.iti_jitter_max_s < 0:
            raise ValueError("ITI values must be non-negative")
        if self.temporal_frequency_hz <= 0 or self.spatial_frequency_cycles_per_cm <= 0:
            raise ValueError("frequencies must be positive")
        if not 0 <= self.contrast <= 1 or not 0 < self.mean_luminance < 1:
            raise ValueError("contrast/luminance values are invalid")
        if self.mean_luminance * (1 + self.contrast) > 1:
            raise ValueError("mean_luminance and contrast exceed display range")
        if self.grating_mode not in {"fullscreen", "rectangular_patch"}:
            raise ValueError("unsupported grating_mode")
        if self.grating_mode == "rectangular_patch":
            geometry = self.rectangular_patch_geometry
            if geometry is None:
                raise ValueError("rectangular_patch_geometry is required in rectangular_patch mode")
            if any(not math.isfinite(value) for value in vars(geometry).values()):
                raise ValueError("rectangular patch geometry must be finite")
            if geometry.width_cm <= 0 or geometry.height_cm <= 0:
                raise ValueError("rectangular patch dimensions must be positive")
        elif self.rectangular_patch_geometry is not None:
            raise ValueError("rectangular_patch_geometry requires grating_mode='rectangular_patch'")
        if type(self.sequence_seed) is not int:
            raise ValueError("sequence_seed must be an integer")
        object.__setattr__(self, "orientations_deg", orientations)

    @property
    def stimulus_frame_count(self) -> int:
        return max(1, round(self.stim_duration_s * self.refresh_hz))


def _iti_frames(settings: DriftingGratingSettings, rng: random.Random) -> int:
    seconds = settings.iti_base_s + rng.random() * settings.iti_jitter_max_s
    return max(1, round(seconds * settings.refresh_hz))


def build_plan(settings: DriftingGratingSettings) -> SessionPlan:
    stim_frames = settings.stimulus_frame_count
    initial_frames = round(settings.initial_gray_s * settings.refresh_hz)
    final_frames = round(settings.final_gray_s * settings.refresh_hz)
    rng = random.Random(settings.sequence_seed)
    trials = [
        (orientation_id, orientation, repeat_number)
        for orientation_id, orientation in enumerate(settings.orientations_deg, start=1)
        for repeat_number in range(1, settings.trials_per_orientation + 1)
    ]
    rng.shuffle(trials)
    events: list[PlannedEvent] = [
        PlannedEvent("initial-gray", "gray", initial_frames, phase="PRE", photodiode="off")
    ]
    for trial_index, (orientation_id, orientation, repeat_number) in enumerate(trials, start=1):
        iti_frames = _iti_frames(settings, rng)
        events.append(
            PlannedEvent(
                f"trial-{trial_index}",
                "drifting-grating",
                stim_frames,
                trial_id=str(trial_index),
                sequence_id=f"orientation-{orientation_id}",
                photodiode="on",
                metadata={
                    "orientation_id": orientation_id,
                    "bar_orientation_deg": orientation,
                    "drift_direction_deg": drift_direction_deg(orientation),
                    "repeat_number": repeat_number,
                    "starting_phase_deg": settings.starting_phase_deg,
                    "temporal_frequency_hz": settings.temporal_frequency_hz,
                    "spatial_frequency_cycles_per_cm": settings.spatial_frequency_cycles_per_cm,
                },
            )
        )
        events.append(
            PlannedEvent(
                f"iti-{trial_index}",
                "iti",
                iti_frames,
                trial_id=str(trial_index),
                photodiode="off",
            )
        )
    events.append(PlannedEvent("final-gray", "gray", final_frames, phase="POST", photodiode="off"))
    return SessionPlan(
        "drifting-gratings",
        settings.sequence_seed,
        with_frame_offsets(events),
        metadata={"orientations_deg": list(settings.orientations_deg)},
    )


class DriftingGratingsProtocol:
    name = "drifting-gratings"
    version = "unified-0.1"

    def build_plan(self, settings: DriftingGratingSettings) -> SessionPlan:
        return build_plan(settings)


protocol = DriftingGratingsProtocol()
