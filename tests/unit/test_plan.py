import json
import random

import pytest

from rpi_vstim.core.duration import seconds_to_frames
from rpi_vstim.core.plan import (
    PlannedEvent,
    SessionPlan,
    no_adjacent_repeat,
    seeded_choices,
    with_frame_offsets,
)


def test_plan_replays_deterministically_and_does_not_touch_global_rng():
    random.seed(91)
    expected_next = random.random()
    random.seed(91)
    first = no_adjacent_repeat(("a", "b", "c"), 12, seed=3)
    actual_next = random.random()

    assert first == no_adjacent_repeat(("a", "b", "c"), 12, seed=3)
    assert actual_next == expected_next
    assert all(left != right for left, right in zip(first, first[1:]))


def test_frame_durations_and_seeded_choices_cover_edges():
    assert seconds_to_frames(0.5, 60.0) == 30
    assert seconds_to_frames(0.0, 60.0) == 0
    assert seeded_choices((30, 60), 4, seed=5) == seeded_choices((30, 60), 4, seed=5)
    assert no_adjacent_repeat(("only",), 3, seed=1) == ("only",) * 3
    assert no_adjacent_repeat((), 0, seed=1) == ()
    with pytest.raises(ValueError):
        no_adjacent_repeat((), 1, seed=1)


def test_plan_serialization_is_stable_and_offsets_are_explicit():
    events = (
        PlannedEvent("pre", "gray", 2, phase="PRE"),
        PlannedEvent("trial-1", "image", 3, trial_id="1", photodiode="on"),
    )
    plan = SessionPlan("natural-images", 7, with_frame_offsets(events))
    payload = json.loads(plan.stable_json())

    assert payload["total_frames"] == 5
    assert payload["events"][0]["planned_start_frame"] == 0
    assert payload["events"][1]["planned_start_frame"] == 2
