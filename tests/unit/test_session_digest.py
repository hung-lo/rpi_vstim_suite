import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import run_simulated_session
from rpi_vstim.core.session_digest import canonical_session, session_digest
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan


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
