import json
import random
from pathlib import Path

import pytest

from rpi_vstim.protocols.drifting_gratings import (
    DriftingGratingSettings,
    build_plan as build_grating_plan,
)
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan as build_natural_plan
from rpi_vstim.protocols.retinotopy import RetinotopySettings, build_plan as build_retinotopy_plan
from rpi_vstim.protocols.reward_conditioning import (
    MouseAssignment,
    RewardConditioningSettings,
    build_plan as build_reward_plan,
)
from rpi_vstim.protocols.spout_training import (
    SpoutTrainingSettings,
    SpoutTrainingState,
    build_plan as build_spout_plan,
    build_training_intervals,
    evaluate_training_criterion,
)


GOLDEN = json.loads(
    (Path(__file__).parents[1] / "golden" / "protocol_plans.json").read_text(encoding="utf-8")
)


def test_natural_counts_profiles_and_golden_schedule():
    plan = build_natural_plan(
        NaturalImageSettings(
            images=("a", "b", "c", "d"),
            image_count=3,
            repeat_count=2,
            seed=7,
            initial_gray_frames=1,
            final_gray_frames=1,
            image_duration_s=1 / 60,
            iti_frames=(2, 4),
        )
    )
    expected = GOLDEN["natural_images"]
    assert plan.metadata["selected_images"] == expected["selected_images"]
    assert [event.kind for event in plan.events] == expected["event_kinds"]
    assert [event.frame_count for event in plan.events] == expected["frame_counts"]
    assert len(plan.metadata["selected_images"]) == 3 * 2
    assert all(
        left != right
        for left, right in zip(plan.metadata["selected_images"], plan.metadata["selected_images"][1:])
    )
    assert build_natural_plan(
        NaturalImageSettings(
            images=("a", "b"), image_count=2, repeat_count=1, compatibility_profile="natural_legacy_camera"
        )
    ).events[-2].kind == "image"
    with pytest.raises(ValueError, match="selection count"):
        build_natural_plan(NaturalImageSettings(images=("a",), image_count=2))


def test_golden_fixture_provenance_is_explicit():
    for fixture in GOLDEN.values():
        provenance = fixture["provenance"]
        assert provenance["reference_repo"]
        assert len(provenance["frozen_commit"]) == 40
        assert provenance["source_file"]
        assert provenance["source_function"]
        assert provenance["derivation"] in {"legacy execution", "direct source derivation", "new-suite regression"}


def test_gratings_are_seeded_frame_plans_with_photodiode_intent():
    settings = DriftingGratingSettings(
        trials_per_orientation=2,
        sequence_seed=7,
        initial_gray_s=1 / 60,
        final_gray_s=1 / 60,
    )
    plan = build_grating_plan(settings)
    expected = GOLDEN["drifting_gratings"]
    trials = [event for event in plan.events if event.kind == "drifting-grating"]
    assert len(trials) == expected["trial_count"]
    assert [event.metadata["orientation_id"] for event in trials[:8]] == expected["first_orientation_ids"]
    assert all(event.photodiode == "on" for event in trials)
    assert all("pixels" not in event.metadata for event in trials)
    assert plan.stable_json() == build_grating_plan(settings).stable_json()


def test_retinotopy_fixed_and_shuffled_sequences_are_bounded():
    settings = RetinotopySettings(
        repeats_per_direction=2,
        sequence_order_mode="shuffled",
        sequence_seed=7,
        initial_gray_s=1 / 60,
        final_gray_s=1 / 60,
        inter_sweep_gray_s=1 / 60,
        sweep_duration_s=1 / 15,
    )
    plan = build_retinotopy_plan(settings)
    expected = GOLDEN["retinotopy"]
    sweeps = [event for event in plan.events if event.kind == "retinotopy-sweep"]
    assert [event.sequence_id for event in sweeps] == expected["sweep_directions"]
    assert all(event.metadata["direction_code"] in range(4) for event in sweeps)
    assert all(event.photodiode == "on" for event in sweeps)
    assert all(event.frame_count == 4 for event in sweeps)


def test_spout_schedule_criterion_and_water_safety_are_pure():
    settings = SpoutTrainingSettings(max_rewards=4, seed=7)
    assert build_training_intervals(settings) == build_training_intervals(settings)
    plan = build_spout_plan(settings)
    rewards = [event for event in plan.events if event.kind == "training-reward"]
    assert len(rewards) == 4
    assert all(event.metadata["reward_delivered"] is None for event in rewards)
    assert evaluate_training_criterion([True] * 16 + [True] * 4)["criterion_passed"]
    state = SpoutTrainingState(2, 5.0, water_cap_ul=5.0)
    state.record_observed_reward(retrieval_success=True)
    with pytest.raises(ValueError, match="water safeguard"):
        state.record_observed_reward(retrieval_success=True)


def test_spout_plan_has_a_golden_boundary_shape():
    expected = GOLDEN["spout_training"]
    plan = build_spout_plan(SpoutTrainingSettings(max_rewards=4, seed=expected["seed"]))
    assert len(plan.events) == expected["event_count"]
    assert plan.total_frames == expected["total_frames"]
    assert plan.events[0].kind == expected["first_kind"]
    assert plan.events[-1].kind == expected["last_kind"]
    assert sum(event.kind == "training-reward" for event in plan.events) == expected["reward_count"]


def test_reward_golden_schedule_keeps_observation_unknown():
    images = tuple(f"image-{index:02d}.png" for index in range(14))
    expected = GOLDEN["reward_conditioning"]
    plan = build_reward_plan(
        RewardConditioningSettings("mouse", images, blocks=expected["blocks"]),
        MouseAssignment.create("mouse", images, seed=11),
    )
    assert len(plan.events) == expected["event_count"]
    assert sum(event.metadata["reward_eligible"] for event in plan.events) == expected["eligible_count"]
    assert sum(event.metadata["reward_scheduled"] for event in plan.events) == expected["scheduled_count"]
    assert all(event.metadata["reward_delivered"] is expected["reward_delivered"] for event in plan.events)


def test_protocol_plans_do_not_touch_global_random_state():
    random.seed(1234)
    before = random.getstate()
    build_grating_plan(DriftingGratingSettings(trials_per_orientation=1, sequence_seed=99))
    build_retinotopy_plan(RetinotopySettings(repeats_per_direction=1, sequence_seed=99))
    build_training_intervals(SpoutTrainingSettings(max_rewards=2, seed=99))
    assert random.getstate() == before
