from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.core.session import atomic_write_json


class RewardPhase(StrEnum):
    ACQUISITION = "acquisition"
    REVERSAL = "reversal"


@dataclass(frozen=True)
class MouseAssignment:
    mouse_id: str
    high_exposure: tuple[str, ...]
    medium_exposure: tuple[str, ...]
    low_exposure: tuple[str, ...]

    @property
    def all_images(self) -> tuple[str, ...]:
        return self.high_exposure + self.medium_exposure + self.low_exposure

    @classmethod
    def create(cls, mouse_id: str, image_pool: Iterable[str], *, seed: int) -> "MouseAssignment":
        images = tuple(image_pool)
        if len(images) < 14:
            raise ValueError("reward conditioning requires at least 14 images")
        rng = random.Random(seed)
        selected = list(images)
        rng.shuffle(selected)
        return cls(mouse_id, tuple(selected[:4]), tuple(selected[4:8]), tuple(selected[8:14]))

    def as_dict(self) -> dict[str, object]:
        return {
            "mouse_id": self.mouse_id,
            "high_exposure": list(self.high_exposure),
            "medium_exposure": list(self.medium_exposure),
            "low_exposure": list(self.low_exposure),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "MouseAssignment":
        assignment = cls(
            str(value["mouse_id"]),
            tuple(value["high_exposure"]),
            tuple(value["medium_exposure"]),
            tuple(value["low_exposure"]),
        )
        if len(assignment.all_images) != 14 or len(set(assignment.all_images)) != 14:
            raise ValueError("stored mouse assignment must contain 14 unique images")
        return assignment


class AssignmentStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, mouse_id: str) -> Path:
        if not mouse_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in mouse_id):
            raise ValueError("mouse_id contains unsupported characters")
        return self.root / f"{mouse_id}.json"

    def load(self, mouse_id: str) -> MouseAssignment | None:
        path = self.path_for(mouse_id)
        if not path.is_file():
            return None
        import json

        return MouseAssignment.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, assignment: MouseAssignment) -> None:
        atomic_write_json(self.path_for(assignment.mouse_id), assignment.as_dict())

    def load_or_create(self, mouse_id: str, image_pool: Iterable[str], *, seed: int) -> MouseAssignment:
        existing = self.load(mouse_id)
        if existing is not None:
            return existing
        assignment = MouseAssignment.create(mouse_id, image_pool, seed=seed)
        self.save(assignment)
        return assignment


@dataclass(frozen=True)
class RewardTrial:
    trial_id: str
    image: str
    exposure_role: str
    reward_scheduled: bool
    lick_count: int = 0

    @property
    def reward_delivered(self) -> bool:
        return self.reward_scheduled

    def as_dict(self) -> dict[str, object]:
        return {
            "trial_id": self.trial_id,
            "image": self.image,
            "exposure_role": self.exposure_role,
            "reward_scheduled": self.reward_scheduled,
            "reward_delivered": self.reward_delivered,
            "lick_count": self.lick_count,
        }


def build_exposure_block(assignment: MouseAssignment, *, seed: int) -> tuple[RewardTrial, ...]:
    """Build one exact 8:3:1 exposure block without hardware effects."""
    roles = (
        [("high", assignment.high_exposure)] * 8
        + [("medium", assignment.medium_exposure)] * 3
        + [("low", assignment.low_exposure)]
    )
    rng = random.Random(seed)
    rng.shuffle(roles)
    return tuple(
        RewardTrial(str(index + 1), rng.choice(images), role, reward_scheduled=False)
        for index, (role, images) in enumerate(roles)
    )


def build_reward_outcomes(
    count: int = 220,
    *,
    seed: int = 0,
    reward_probability: float = 0.9,
) -> tuple[bool, ...]:
    if count < 0 or not 0.0 <= reward_probability <= 1.0:
        raise ValueError("invalid reward schedule settings")
    rewarded = round(count * reward_probability)
    outcomes = [True] * rewarded + [False] * (count - rewarded)
    random.Random(seed).shuffle(outcomes)
    return tuple(outcomes)


@dataclass
class WaterBudget:
    maximum_ul: int
    delivered_ul: int = 0

    def record_delivery(self, volume_ul: int) -> None:
        if volume_ul < 0 or self.delivered_ul + volume_ul > self.maximum_ul:
            raise ValueError("water safeguard limit exceeded")
        self.delivered_ul += volume_ul


@dataclass
class PhaseState:
    phase: RewardPhase = RewardPhase.ACQUISITION

    def begin_reversal(self, *, manual: bool) -> None:
        if not manual:
            raise ValueError("reversal requires an explicit manual selection")
        self.phase = RewardPhase.REVERSAL


@dataclass(frozen=True)
class RewardConditioningSettings:
    mouse_id: str
    image_pool: tuple[str, ...]
    seed: int = 0
    blocks: int = 1
    refresh_hz: float = 60.0
    trial_frames: int = 90
    reward_boundary_frames: int = 60


def build_plan(settings: RewardConditioningSettings) -> SessionPlan:
    if settings.blocks < 0:
        raise ValueError("blocks must be non-negative")
    assignment = MouseAssignment.create(settings.mouse_id, settings.image_pool, seed=settings.seed)
    outcomes = build_reward_outcomes(settings.blocks * 12, seed=settings.seed + 1)
    events: list[PlannedEvent] = []
    index = 0
    for block in range(settings.blocks):
        block_trials = build_exposure_block(assignment, seed=settings.seed + block)
        for trial in block_trials:
            scheduled = outcomes[index]
            index += 1
            events.append(
                PlannedEvent(
                    f"trial-{index}",
                    "rewarded-image",
                    settings.trial_frames,
                    trial_id=str(index),
                    sequence_id=f"block-{block + 1}",
                    photodiode="on",
                    metadata={
                        "image": trial.image,
                        "exposure_role": trial.exposure_role,
                        "reward_scheduled": scheduled,
                        "reward_boundary_frames": settings.reward_boundary_frames,
                    },
                )
            )
    return SessionPlan(
        "reward-conditioning",
        settings.seed,
        with_frame_offsets(events),
        metadata={"mouse_id": settings.mouse_id, "blocks": settings.blocks},
    )


class RewardConditioningProtocol:
    name = "reward-conditioning"
    version = "software-groundwork"

    def build_plan(self, settings: RewardConditioningSettings) -> SessionPlan:
        return build_plan(settings)


protocol = RewardConditioningProtocol()
