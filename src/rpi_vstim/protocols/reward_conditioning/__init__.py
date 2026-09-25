from __future__ import annotations

import json
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.core.session import atomic_write_json


PROTOCOL_VERSION = "exposure_reward_partial_reversal_v1"


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

    def reward_images(self, phase: RewardPhase) -> frozenset[str]:
        if phase == RewardPhase.ACQUISITION:
            indexes = (0, 1)
        elif phase == RewardPhase.REVERSAL:
            indexes = (0, 2)
        else:
            raise ValueError(f"unsupported reward phase: {phase}")
        return frozenset(
            [self.high_exposure[index] for index in indexes]
            + [self.medium_exposure[index] for index in indexes]
        )

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
        return self.root / f"{mouse_id}_exposure_reward_v1_assignment.json"

    def load(self, mouse_id: str) -> MouseAssignment | None:
        path = self.path_for(mouse_id)
        if not path.is_file():
            return None
        assignment = MouseAssignment.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if assignment.mouse_id != mouse_id:
            raise ValueError("stored assignment mouse_id does not match requested mouse_id")
        return assignment

    def save(self, assignment: MouseAssignment) -> None:
        atomic_write_json(self.path_for(assignment.mouse_id), assignment.as_dict())

    def load_or_create(self, mouse_id: str, image_pool: Iterable[str], *, seed: int) -> MouseAssignment:
        available_images = tuple(image_pool)
        existing = self.load(mouse_id)
        if existing is not None:
            missing = set(existing.all_images) - set(available_images)
            if missing:
                raise ValueError("stored assignment references images missing from current image pool")
            return existing
        assignment = MouseAssignment.create(mouse_id, available_images, seed=seed)
        self.save(assignment)
        return assignment


class PhaseStateStore:
    """Separate persistent phase file matching the legacy runner's contract."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, mouse_id: str) -> Path:
        if not mouse_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for char in mouse_id
        ):
            raise ValueError("mouse_id contains unsupported characters")
        return self.root / f"{mouse_id}_reward_conditioning_state.json"

    def load(self, mouse_id: str) -> "PhaseState | None":
        path = self.path_for(mouse_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported reward phase state")
        state = PhaseState.from_dict(value)
        if state.mouse_id != mouse_id:
            raise ValueError("stored phase state mouse_id does not match requested mouse_id")
        return state

    def save(self, state: "PhaseState") -> None:
        atomic_write_json(self.path_for(state.mouse_id), state.as_dict())

    def load_or_create(self, mouse_id: str) -> "PhaseState":
        state = self.load(mouse_id)
        if state is not None:
            return state
        state = PhaseState(mouse_id=mouse_id)
        self.save(state)
        return state


@dataclass(frozen=True)
class RewardTrial:
    trial_id: str
    image: str
    exposure_role: str
    reward_scheduled: bool
    reward_eligible: bool = False
    suction_scheduled: bool = False
    reward_delivered: bool | None = None
    lick_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "trial_id": self.trial_id,
            "image": self.image,
            "exposure_role": self.exposure_role,
            "reward_scheduled": self.reward_scheduled,
            "reward_eligible": self.reward_eligible,
            "suction_scheduled": self.suction_scheduled,
            "reward_delivered": self.reward_delivered,
            "lick_count": self.lick_count,
        }


def build_exposure_block(
    assignment: MouseAssignment,
    *,
    seed: int,
    phase: RewardPhase = RewardPhase.ACQUISITION,
) -> tuple[RewardTrial, ...]:
    """Build one frozen 50-trial block: 8:3:1 per image exposure tier."""
    rows = (
        [("high", image) for image in assignment.high_exposure for _ in range(8)]
        + [("medium", image) for image in assignment.medium_exposure for _ in range(3)]
        + [("low", image) for image in assignment.low_exposure]
    )
    rng = random.Random(seed)
    reward_images = assignment.reward_images(phase)
    for _ in range(1000):
        rng.shuffle(rows)
        if all(left[1] != right[1] for left, right in zip(rows, rows[1:])):
            break
    else:
        raise RuntimeError("could not construct a non-repeating exposure block")
    return tuple(
        RewardTrial(
            str(index + 1),
            image,
            role,
            reward_scheduled=False,
            reward_eligible=image in reward_images,
            suction_scheduled=image in reward_images,
        )
        for index, (role, image) in enumerate(rows)
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
    mouse_id: str = ""
    phase: RewardPhase = RewardPhase.ACQUISITION
    reversal_has_started: bool = False
    first_reversal_session_id: str | None = None

    def begin_reversal(self, *, manual: bool, session_id: str | None = None) -> None:
        if not manual:
            raise ValueError("reversal requires an explicit manual selection")
        self.phase = RewardPhase.REVERSAL
        self.reversal_has_started = True
        if self.first_reversal_session_id is None:
            self.first_reversal_session_id = session_id

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mouse_id": self.mouse_id,
            "protocol_version": PROTOCOL_VERSION,
            "current_phase": self.phase.value,
            "reversal_has_started": self.reversal_has_started,
            "first_reversal_session_id": self.first_reversal_session_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PhaseState":
        return cls(
            mouse_id=str(value["mouse_id"]),
            phase=RewardPhase(value.get("current_phase", "acquisition")),
            reversal_has_started=bool(value.get("reversal_has_started", False)),
            first_reversal_session_id=value.get("first_reversal_session_id"),
        )


@dataclass(frozen=True)
class RewardConditioningSettings:
    mouse_id: str
    image_pool: tuple[str, ...]
    seed: int = 0
    blocks: int = 10
    refresh_hz: float = 60.0
    trial_frames: int = 90
    reward_boundary_frames: int = 60
    phase: RewardPhase = RewardPhase.ACQUISITION


def build_plan(
    settings: RewardConditioningSettings,
    assignment: MouseAssignment,
    phase_state: PhaseState | None = None,
) -> SessionPlan:
    if settings.blocks < 1 or settings.blocks % 10:
        raise ValueError("blocks must be a positive multiple of 10")
    if settings.trial_frames < 1:
        raise ValueError("trial_frames must be at least 1")
    if not 0 <= settings.reward_boundary_frames <= settings.trial_frames:
        raise ValueError("reward_boundary_frames must be within trial_frames")
    if assignment.mouse_id != settings.mouse_id:
        raise ValueError("assignment mouse_id does not match settings")
    phase = phase_state.phase if phase_state is not None else settings.phase
    blocks = [
        build_exposure_block(assignment, seed=settings.seed + block, phase=phase)
        for block in range(settings.blocks)
    ]
    eligible_count = sum(trial.reward_eligible for block in blocks for trial in block)
    outcomes = iter(build_reward_outcomes(eligible_count, seed=settings.seed + 1))
    events: list[PlannedEvent] = []
    index = 0
    for block, block_trials in enumerate(blocks):
        for trial in block_trials:
            index += 1
            if trial.reward_eligible:
                scheduled = next(outcomes)
            else:
                scheduled = False
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
                        "reward_eligible": trial.reward_eligible,
                        "reward_scheduled": scheduled,
                        "reward_delivered": None,
                        "suction_scheduled": trial.suction_scheduled,
                        "reward_boundary_frames": settings.reward_boundary_frames,
                    },
                )
            )
    return SessionPlan(
        "reward-conditioning",
        settings.seed,
        with_frame_offsets(events),
        metadata={"mouse_id": settings.mouse_id, "blocks": settings.blocks, "phase": phase.value},
    )


class RewardConditioningProtocol:
    name = "reward-conditioning"
    version = "software-groundwork"

    def build_plan(
        self,
        settings: RewardConditioningSettings,
        assignment: MouseAssignment,
        phase_state: PhaseState | None = None,
    ) -> SessionPlan:
        return build_plan(settings, assignment, phase_state)


protocol = RewardConditioningProtocol()
