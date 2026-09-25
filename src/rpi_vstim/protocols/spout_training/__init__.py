from __future__ import annotations

import random
from dataclasses import dataclass, field

from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets


@dataclass(frozen=True)
class SpoutTrainingSettings:
    max_rewards: int = 60
    interval_min_s: float = 8.0
    interval_max_s: float = 12.0
    criterion_window: int = 20
    criterion_min_rewards: int = 20
    criterion_fraction: float = 0.80
    reward_volume_ul: float = 5.0
    suction_delay_s: float = 2.5
    refresh_hz: float = 60.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.max_rewards < 1 or self.criterion_window < 1 or self.criterion_min_rewards < 1:
            raise ValueError("reward counts and criterion window must be positive")
        if self.interval_min_s <= 0 or self.interval_max_s < self.interval_min_s:
            raise ValueError("training intervals must satisfy 0 < min <= max")
        if not 0 <= self.criterion_fraction <= 1:
            raise ValueError("criterion_fraction must be within [0, 1]")
        if self.reward_volume_ul < 0 or self.suction_delay_s < 0 or self.refresh_hz <= 0:
            raise ValueError("training safety/timing values are invalid")


def build_training_intervals(settings: SpoutTrainingSettings) -> tuple[float, ...]:
    rng = random.Random(settings.seed)
    return (0.0,) + tuple(
        rng.uniform(settings.interval_min_s, settings.interval_max_s)
        for _ in range(settings.max_rewards - 1)
    )


def anchor_training_schedule(start_monotonic_ns: int, intervals: tuple[float, ...]) -> tuple[dict[str, object], ...]:
    target_ns = int(start_monotonic_ns)
    rows = []
    for index, interval in enumerate(intervals, start=1):
        if index > 1:
            target_ns += round(interval * 1_000_000_000)
        rows.append({
            "training_reward_index": index,
            "planned_interval_sec": interval,
            "planned_reward_target_monotonic_ns": target_ns,
        })
    return tuple(rows)


def evaluate_training_criterion(
    successes: list[bool] | tuple[bool, ...],
    *,
    minimum_rewards: int = 20,
    window: int = 20,
    fraction: float = 0.80,
) -> dict[str, object]:
    if minimum_rewards < 1 or window < 1 or not 0 <= fraction <= 1:
        raise ValueError("invalid training criterion configuration")
    recent = [bool(value) for value in successes[-window:]]
    count = sum(recent)
    recent_fraction = count / len(recent) if recent else None
    evaluable = len(successes) >= minimum_rewards and len(recent) >= window
    return {
        "recent_success_count": count,
        "recent_success_fraction": recent_fraction,
        "criterion_evaluable": evaluable,
        "criterion_passed": bool(evaluable and recent_fraction >= fraction),
    }


@dataclass
class SpoutTrainingState:
    maximum_training_rewards: int
    reward_volume_ul: float
    water_cap_ul: float | None = None
    successes: list[bool] = field(default_factory=list)
    delivered_water_ul: float = 0.0

    def record_observed_reward(self, *, retrieval_success: bool, delivered: bool = True) -> dict[str, object]:
        if len(self.successes) >= self.maximum_training_rewards:
            raise ValueError("maximum training rewards exceeded")
        if delivered:
            if self.water_cap_ul is not None and self.delivered_water_ul + self.reward_volume_ul > self.water_cap_ul:
                raise ValueError("water safeguard limit exceeded")
            self.delivered_water_ul += self.reward_volume_ul
        self.successes.append(bool(retrieval_success))
        return evaluate_training_criterion(self.successes)


def build_plan(settings: SpoutTrainingSettings) -> SessionPlan:
    intervals = build_training_intervals(settings)
    events: list[PlannedEvent] = [PlannedEvent("training-start", "gray", 1, phase="PRE")]
    for index, interval in enumerate(intervals, start=1):
        if interval:
            events.append(PlannedEvent(
                f"wait-{index}", "training-interval", max(1, round(interval * settings.refresh_hz)),
                trial_id=str(index), photodiode="off", metadata={"planned_interval_sec": interval},
            ))
        events.append(PlannedEvent(
            f"reward-{index}", "training-reward", 1, trial_id=str(index),
            sequence_id=f"reward-{index}", photodiode="off",
            metadata={
                "reward_scheduled": True, "reward_delivered": None,
                "reward_volume_ul": settings.reward_volume_ul,
                "suction_delay_s": settings.suction_delay_s,
            },
        ))
    events.append(PlannedEvent("training-end", "gray", 1, phase="POST"))
    return SessionPlan(
        "spout-training", settings.seed, with_frame_offsets(events),
        metadata={
            "max_rewards": settings.max_rewards,
            "criterion_window": settings.criterion_window,
            "criterion_fraction": settings.criterion_fraction,
        },
    )


class SpoutTrainingProtocol:
    name = "spout-training"
    version = "software-groundwork"

    def build_plan(self, settings: SpoutTrainingSettings) -> SessionPlan:
        return build_plan(settings)


protocol = SpoutTrainingProtocol()
