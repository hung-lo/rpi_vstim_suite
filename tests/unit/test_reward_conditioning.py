import json

import pytest

from rpi_vstim.protocols.reward_conditioning import (
    AssignmentStore,
    MouseAssignment,
    PhaseState,
    RewardConditioningSettings,
    RewardPhase,
    WaterBudget,
    build_exposure_block,
    build_plan,
    build_reward_outcomes,
)


def image_pool():
    return tuple(f"image-{index:02d}.png" for index in range(14))


def test_assignment_is_permanent_and_uses_temporary_state(tmp_path):
    store = AssignmentStore(tmp_path)
    first = store.load_or_create("mouse-1", image_pool(), seed=4)
    second = store.load_or_create("mouse-1", tuple(reversed(image_pool())), seed=99)

    assert first == second
    assert json.loads(store.path_for("mouse-1").read_text())["mouse_id"] == "mouse-1"


def test_exposure_block_has_exact_8_3_1_counts():
    block = build_exposure_block(MouseAssignment.create("m", image_pool(), seed=1), seed=2)
    counts = {role: sum(trial.exposure_role == role for trial in block) for role in ("high", "medium", "low")}
    assert counts == {"high": 8, "medium": 3, "low": 1}


def test_reward_outcomes_are_reproducible_and_match_90_percent_count():
    outcomes = build_reward_outcomes(seed=8)
    assert outcomes == build_reward_outcomes(seed=8)
    assert sum(outcomes) == 198
    assert len(outcomes) - sum(outcomes) == 22


def test_phase_reversal_requires_manual_selection_and_water_is_guarded():
    phase = PhaseState()
    with pytest.raises(ValueError):
        phase.begin_reversal(manual=False)
    phase.begin_reversal(manual=True)
    assert phase.phase == RewardPhase.REVERSAL

    budget = WaterBudget(maximum_ul=10)
    budget.record_delivery(10)
    with pytest.raises(ValueError):
        budget.record_delivery(1)


def test_reward_plan_is_deterministic_and_does_not_actuate_hardware():
    settings = RewardConditioningSettings("mouse-1", image_pool(), seed=2, blocks=2)
    first = build_plan(settings)
    second = build_plan(settings)
    assert first.stable_json() == second.stable_json()
    assert len(first.events) == 24
    assert all(event.metadata["reward_boundary_frames"] == 60 for event in first.events)
