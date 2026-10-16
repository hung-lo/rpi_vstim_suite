import json

import pytest

from rpi_vstim.protocols.reward_conditioning import (
    AssignmentStore,
    MouseAssignment,
    PhaseState,
    PhaseStateStore,
    RewardConditioningSettings,
    RewardPhase,
    WaterBudget,
    build_exposure_block,
    build_exact_role_reward_outcomes,
    build_plan,
    build_reward_outcomes,
    ALL_ROLES,
    HIGH_ROLES,
    MEDIUM_ROLES,
)


def image_pool():
    return tuple(f"image-{index:02d}.png" for index in range(14))


def test_assignment_is_permanent_and_uses_temporary_state(tmp_path):
    store = AssignmentStore(tmp_path)
    first = store.load_or_create("mouse-1", image_pool(), seed=4)
    second = store.load_or_create("mouse-1", tuple(reversed(image_pool())), seed=99)

    assert first == second
    assert json.loads(store.path_for("mouse-1").read_text())["mouse_id"] == "mouse-1"


def test_persistent_assignment_and_phase_state_reject_mismatched_identity(tmp_path):
    assignment_store = AssignmentStore(tmp_path)
    payload = MouseAssignment.create("mouse-1", image_pool(), seed=4).as_dict()
    payload["mouse_id"] = "mouse-2"
    assignment_store.path_for("mouse-1").parent.mkdir(parents=True, exist_ok=True)
    assignment_store.path_for("mouse-1").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="assignment mouse_id"):
        assignment_store.load("mouse-1")

    phase_store = PhaseStateStore(tmp_path)
    state_payload = PhaseState(mouse_id="mouse-2").as_dict()
    phase_store.path_for("mouse-1").write_text(json.dumps(state_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="phase state mouse_id"):
        phase_store.load("mouse-1")


def test_existing_assignment_rejects_missing_current_image(tmp_path):
    store = AssignmentStore(tmp_path)
    store.load_or_create("mouse-1", image_pool(), seed=4)
    with pytest.raises(ValueError, match="missing from current image pool"):
        store.load_or_create("mouse-1", image_pool()[:-1], seed=99)


def test_exposure_block_has_exact_8_3_1_counts():
    block = build_exposure_block(MouseAssignment.create("m", image_pool(), seed=1), seed=2)
    counts = {role: sum(trial.exposure_role == role for trial in block) for role in ("high", "medium", "low")}
    assert counts == {"high": 32, "medium": 12, "low": 6}
    assert all(left.image != right.image for left, right in zip(block, block[1:]))


def test_reward_roles_match_frozen_trajectory_metadata_and_exact_schedule():
    assignment = MouseAssignment.create("m", image_pool(), seed=1)
    block = build_exposure_block(assignment, seed=2)
    assert {trial.image_role for trial in block} == set(ALL_ROLES)
    assert {trial.current_reward_state for trial in block if trial.reward_eligible} == {"R"}
    trials = block * 10
    outcomes = build_exact_role_reward_outcomes(
        trials,
        phase=RewardPhase.ACQUISITION,
        seed=8,
    )
    for role in ("high_R_to_R", "high_R_to_U", "medium_R_to_R", "medium_R_to_U"):
        role_outcomes = [outcomes[index] for index, trial in enumerate(trials) if trial.image_role == role]
        assert sum(role_outcomes) == len(role_outcomes) * 9 // 10


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
    settings = RewardConditioningSettings("mouse-1", image_pool(), seed=2, blocks=10)
    assignment = MouseAssignment.create("mouse-1", image_pool(), seed=100)
    first = build_plan(settings, assignment)
    second = build_plan(settings, assignment)
    assert first.stable_json() == second.stable_json()
    assert len(first.events) == 500
    assert sum(event.metadata["reward_scheduled"] for event in first.events) == 198
    assert sum(event.metadata["reward_eligible"] for event in first.events) == 220
    assert all(event.metadata["reward_boundary_frames"] == 60 for event in first.events)
    assert all(event.metadata["reward_scheduled"] is not None for event in first.events)


def test_reward_exposure_fallback_handles_seed_133():
    assignment = MouseAssignment.create("mouse-1", image_pool(), seed=100)
    plan = build_plan(
        RewardConditioningSettings("mouse-1", image_pool(), seed=133, blocks=10), assignment
    )
    image_names = [event.metadata["image"] for event in plan.events]
    assert all(left != right for left, right in zip(image_names, image_names[1:]))
