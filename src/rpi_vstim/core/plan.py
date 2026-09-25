"""Small deterministic plan primitives shared by simulated protocols."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, replace
from typing import Any, Iterable


@dataclass(frozen=True)
class PlannedEvent:
    event_id: str
    kind: str
    frame_count: int
    phase: str = "TASK"
    trial_id: str | None = None
    sequence_id: str | None = None
    photodiode: str = "off"
    planned_start_frame: int = 0
    planned_utc_ns: int | None = None
    observed_utc_ns: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.frame_count < 0:
            raise ValueError("frame_count must be non-negative")
        if self.planned_start_frame < 0:
            raise ValueError("planned_start_frame must be non-negative")
        if self.photodiode not in {"on", "off"}:
            raise ValueError("photodiode must be 'on' or 'off'")

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "frame_count": self.frame_count,
            "phase": self.phase,
            "trial_id": self.trial_id,
            "sequence_id": self.sequence_id,
            "photodiode": self.photodiode,
            "planned_start_frame": self.planned_start_frame,
            "planned_utc_ns": self.planned_utc_ns,
            "observed_utc_ns": self.observed_utc_ns,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SessionPlan:
    protocol: str
    seed: int
    events: tuple[PlannedEvent, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_frames(self) -> int:
        return sum(event.frame_count for event in self.events)

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "seed": self.seed,
            "total_frames": self.total_frames,
            "metadata": self.metadata,
            "events": [event.as_dict() for event in self.events],
        }

    def stable_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


def with_frame_offsets(events: Iterable[PlannedEvent]) -> tuple[PlannedEvent, ...]:
    offset = 0
    planned: list[PlannedEvent] = []
    for event in events:
        planned.append(replace(event, planned_start_frame=offset))
        offset += event.frame_count
    return tuple(planned)


def no_adjacent_repeat(items: Iterable[str], count: int, *, seed: int) -> tuple[str, ...]:
    values = tuple(items)
    if count < 0:
        raise ValueError("count must be non-negative")
    if count and not values:
        raise ValueError("cannot schedule items from an empty collection")
    if len(values) == 1:
        return values * count
    rng = random.Random(seed)
    result: list[str] = []
    for _ in range(count):
        choices = [value for value in values if not result or value != result[-1]]
        result.append(rng.choice(choices))
    return tuple(result)


def seeded_choices(values: Iterable[int], count: int, *, seed: int) -> tuple[int, ...]:
    values = tuple(values)
    if count < 0:
        raise ValueError("count must be non-negative")
    if count and not values:
        raise ValueError("cannot choose from an empty collection")
    rng = random.Random(seed)
    return tuple(rng.choice(values) for _ in range(count))
