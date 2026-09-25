from __future__ import annotations

import random
from dataclasses import dataclass

from rpi_vstim.core.duration import seconds_to_frames
from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets


DEFAULT_ORIENTATIONS_DEG = (0.0, 22.5, 45.0, 67.5, 90.0, 112.5, 135.0, 157.5)


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

    def __post_init__(self) -> None:
        orientations = tuple(normalize_orientation_deg(value) for value in self.orientations_deg)
        if not orientations or len(set(orientations)) != len(orientations):
            raise ValueError("orientations must be unique and non-empty")
        if self.trials_per_orientation < 1:
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
        object.__setattr__(self, "orientations_deg", orientations)


def _iti_frames(settings: DriftingGratingSettings, rng: random.Random) -> int:
    seconds = settings.iti_base_s + rng.random() * settings.iti_jitter_max_s
    return max(1, round(seconds * settings.refresh_hz))


def build_plan(settings: DriftingGratingSettings) -> SessionPlan:
    stim_frames = seconds_to_frames(settings.stim_duration_s, settings.refresh_hz)
    initial_frames = seconds_to_frames(settings.initial_gray_s, settings.refresh_hz)
    final_frames = seconds_to_frames(settings.final_gray_s, settings.refresh_hz)
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
                _iti_frames(settings, rng),
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
    version = "software-groundwork"

    def build_plan(self, settings: DriftingGratingSettings) -> SessionPlan:
        return build_plan(settings)


protocol = DriftingGratingsProtocol()
