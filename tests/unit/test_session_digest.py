import json
from pathlib import Path

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.core.session_digest import canonical_session, session_digest
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


SESSION_GOLDEN = json.loads(
    (Path(__file__).parents[1] / "golden" / "session_digests.json").read_text(encoding="utf-8")
)


def _plan():
    return build_plan(NaturalImageSettings(
        images=("a", "b"), trial_count=2, initial_gray_frames=1,
        final_gray_frames=1, image_duration_s=1 / 60, iti_frames=(1,), seed=17,
    ))


def test_full_session_digest_ignores_timestamps_and_paths(tmp_path):
    config = config_from_mapping({"paths": {"output_root": tmp_path / "one"}})
    first = run_simulated_session(config, plan=_plan(), session_id="same", seed=17)
    config = config_from_mapping({"paths": {"output_root": tmp_path / "two"}})
    second = run_simulated_session(config, plan=_plan(), session_id="same", seed=17)
    assert first.final_state.value == second.final_state.value == "COMPLETE"
    assert session_digest(first.session.context.session_root) == session_digest(second.session.context.session_root)
    value = canonical_session(first.session.context.session_root)
    assert value["plan"]["schema_version"] == 1
    assert value["final"]["status"] == "COMPLETE"


def test_full_session_digest_changes_with_behavior(tmp_path):
    first = run_simulated_session(
        config_from_mapping({"paths": {"output_root": tmp_path / "one"}}),
        plan=_plan(), session_id="same", seed=17,
    )
    changed_plan = build_plan(NaturalImageSettings(
        images=("a", "b"), trial_count=2, initial_gray_frames=1,
        final_gray_frames=1, image_duration_s=2 / 60, iti_frames=(1,), seed=17,
    ))
    second = run_simulated_session(
        config_from_mapping({"paths": {"output_root": tmp_path / "two"}}),
        plan=changed_plan, session_id="same", seed=17,
    )
    assert session_digest(first.session.context.session_root) != session_digest(second.session.context.session_root)


def test_representative_protocol_sessions_match_golden_digests(tmp_path):
    cases = {
        "natural-images": {"images": ["a", "b"], "image_count": 2, "repeat_count": 1, "initial_gray_frames": 1, "final_gray_frames": 1, "image_duration_s": 1 / 60, "iti_frames": [1]},
        "reward-conditioning": {"images": [f"image-{index:02d}.png" for index in range(14)], "blocks": 10, "trial_frames": 1, "reward_boundary_frames": 0},
        "spout-training": {"max_rewards": 2, "interval_min_s": 1 / 60, "interval_max_s": 1 / 60},
        "drifting-gratings": {"orientations_deg": [0.0, 90.0], "trials_per_orientation": 1, "stim_duration_s": 1 / 60, "iti_base_s": 1 / 60, "iti_jitter_max_s": 0.0, "initial_gray_s": 1 / 60, "final_gray_s": 1 / 60},
        "retinotopy": {"enabled_directions": ["left_to_right"], "repeats_per_direction": 1, "sweep_duration_s": 1 / 15, "inter_sweep_gray_s": 1 / 60, "initial_gray_s": 1 / 60, "final_gray_s": 1 / 60},
    }
    for protocol, parameters in cases.items():
        config = config_from_mapping({
            "paths": {"output_root": tmp_path},
            "protocol": {"name": protocol, "version": "software-groundwork", **parameters},
        })
        result = run_simulated_session(config, protocol_name=protocol, session_id=protocol, seed=17)
        assert result.final_state.value == "COMPLETE"
        assert session_digest(result.session.context.session_root) == SESSION_GOLDEN[protocol]
