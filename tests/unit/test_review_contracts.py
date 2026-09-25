import json

import pytest

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState, RuntimeServices
from rpi_vstim.core.plan import PlannedEvent, SessionPlan
from rpi_vstim.core.runtime import build_simulated_services, run_simulated_session
from rpi_vstim.core.session import SessionOutput
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan as build_natural_plan
from rpi_vstim.protocols.reward_conditioning import (
    AssignmentStore,
    MouseAssignment,
    PhaseStateStore,
    RewardConditioningSettings,
    RewardTrial,
    build_plan as build_reward_plan,
)
from rpi_vstim.telemetry.payloads import TelemetryMessage


def reward_images():
    return tuple(f"image-{index:02d}.png" for index in range(14))


def test_assignment_and_phase_files_persist_independently(tmp_path):
    assignment_store = AssignmentStore(tmp_path)
    phase_store = PhaseStateStore(tmp_path)
    first = assignment_store.load_or_create("mouse-1", reward_images(), seed=1)
    second = assignment_store.load_or_create("mouse-1", tuple(reversed(reward_images())), seed=99)
    state = phase_store.load_or_create("mouse-1")
    state.begin_reversal(manual=True, session_id="session-1")
    phase_store.save(state)

    assert first == second
    assert phase_store.load("mouse-1").phase.value == "reversal"
    assert phase_store.load("mouse-1").first_reversal_session_id == "session-1"
    assert assignment_store.path_for("mouse-1").name.endswith("_exposure_reward_v1_assignment.json")
    assert phase_store.path_for("mouse-1").name.endswith("_reward_conditioning_state.json")
    assert str(tmp_path) in str(assignment_store.path_for("mouse-1"))


def test_scheduled_reward_is_not_observed_delivery():
    trial = RewardTrial("1", "image.png", "high", reward_scheduled=True, reward_eligible=True)
    assert trial.reward_delivered is None
    assert trial.as_dict()["reward_delivered"] is None


def test_telemetry_matches_monitor_outer_envelope():
    message = TelemetryMessage(
        "trial", "session-1", "reward-conditioning", "TASK", sequence_number=4,
        trial_id="7", stimulus="image-7", counters={"rewards": 1},
        cameras=[{"camera_id": "face", "state": "RECORDING"}],
        error="degraded", degraded=["telemetry"], protocol_version="software-groundwork",
    )
    payload = json.loads(message.to_json())
    assert payload["schema_version"] == 1
    assert payload["telemetry_schema_version"] == 3
    assert payload["type"] == "trial_complete"
    assert payload["timestamp_utc"].endswith("Z")
    assert payload["image"] == "image-7"
    assert payload["rewards"] == 1
    assert TelemetryMessage.from_json(message.to_json()) == message


def test_lifecycle_telemetry_round_trips_as_state_without_changing_internal_semantics():
    message = TelemetryMessage("lifecycle", "session-1", "natural-images", "PRE")
    payload = json.loads(message.to_json())
    restored = TelemetryMessage.from_json(message.to_json())
    assert payload["type"] == "state"
    assert restored.message_type == "lifecycle"
    assert restored == message


def test_telemetry_counters_cannot_overwrite_envelope():
    message = TelemetryMessage(
        "trial", "session-1", "natural-images", "TASK", counters={"schema_version": 99}
    )
    with pytest.raises(ValueError, match="reserved field"):
        message.as_dict()


def test_dual_camera_legacy_summary_is_conservative():
    healthy = TelemetryMessage(
        "lifecycle", "session-1", "natural-images", "TASK",
        cameras=[
            {"camera_id": "face", "state": "RECORDING", "required": True},
            {"camera_id": "behavior", "state": "RECORDING", "required": False},
        ],
    )
    degraded = TelemetryMessage(
        "lifecycle", "session-1", "natural-images", "TASK",
        cameras=[
            {"camera_id": "face", "state": "RECORDING", "required": True},
            {"camera_id": "behavior", "state": "DEGRADED", "required": False},
        ],
    )
    failed = TelemetryMessage(
        "lifecycle", "session-1", "natural-images", "TASK",
        cameras=[
            {"camera_id": "face", "state": "FAILED", "required": True},
            {"camera_id": "behavior", "state": "RECORDING", "required": False},
        ],
    )
    assert json.loads(healthy.to_json())["camera_state"] == "RECORDING"
    assert json.loads(degraded.to_json())["camera_state"] == "DEGRADED"
    assert json.loads(failed.to_json())["camera_state"] == "FAILED"


def test_event_telemetry_failure_is_degraded_or_required(tmp_path):
    optional = config_from_mapping({"paths": {"output_root": tmp_path}})
    required = config_from_mapping({
        "paths": {"output_root": tmp_path / "required"},
        "telemetry": {"enabled": True, "required": True, "host": "monitor"},
    })
    plan = build_natural_plan(NaturalImageSettings(
        images=("a", "b"), trial_count=2, initial_gray_frames=1, final_gray_frames=1,
        iti_frames=(1,), image_duration_s=1 / 60,
    ))

    optional_result = run_simulated_session(
        optional, plan=plan, session_id="optional", telemetry_fail_after=8
    )
    required_result = run_simulated_session(
        required, plan=plan, session_id="required", telemetry_fail_after=8
    )
    assert optional_result.ok and optional_result.degraded == ["telemetry"]
    assert required_result.final_state == LifecycleState.FAILED


def test_cleanup_attempts_every_service_and_preserves_primary_error(tmp_path):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    services = build_simulated_services(config)
    calls = []

    def failing(label):
        def action():
            calls.append(label)
            raise RuntimeError(f"{label} failed")
        return action

    services.hardware.backend.safe = failing("hardware.safe")
    services.hardware.backend.stop = failing("hardware.stop")
    services.cameras.stop = failing("cameras.stop")
    services.display.close = failing("display.close")
    services.telemetry.close = failing("telemetry.close")
    result = run_simulated_session(
        config, session_id="cleanup", protocol_failure=True, services=services
    )
    manifest = json.loads((tmp_path / "cleanup" / "session_manifest.json").read_text())

    assert result.final_state == LifecycleState.CLEANUP_FAILED
    assert result.error == "simulated protocol failure"
    assert calls == ["hardware.safe", "hardware.stop", "cameras.stop", "display.close", "telemetry.close"]
    assert len(manifest["cleanup_errors"]) == 5


def test_invalid_plan_fails_before_session_creation(tmp_path):
    config = config_from_mapping({
        "paths": {"output_root": tmp_path},
        "protocol": {"name": "reward-conditioning", "blocks": 1},
    })
    with pytest.raises(ValueError, match="multiple of 10"):
        run_simulated_session(config, session_id="invalid")
    assert not (tmp_path / "invalid").exists()


def test_plan_output_failure_closes_as_terminal_failure(tmp_path, monkeypatch):
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    def fail_write_plan(self, plan):
        raise OSError("plan output failed")

    monkeypatch.setattr(SessionOutput, "write_plan", fail_write_plan)
    result = run_simulated_session(config, plan=SessionPlan("natural-images", 1, ()), session_id="plan-fail")
    manifest = json.loads((tmp_path / "plan-fail" / "session_manifest.json").read_text())
    assert result.final_state == LifecycleState.FAILED
    assert result.error == "plan output failed"
    assert manifest["status"] == "FAILED"


def test_invalid_phase_and_zero_frame_events_are_consistent(tmp_path):
    with pytest.raises(ValueError, match="unsupported plan phase"):
        PlannedEvent("bad", "gray", 1, phase="MIDDLE")
    config = config_from_mapping({"paths": {"output_root": tmp_path}})
    plan = SessionPlan(
        "natural-images", 1,
        (PlannedEvent("noop", "metadata", 0, phase="TASK"),),
    )
    result = run_simulated_session(config, plan=plan, session_id="zero")
    assert result.ok
    assert result.services.display.presented == []


def test_reward_timing_and_persistence_are_explicit():
    assignment = MouseAssignment.create("mouse", reward_images(), seed=1)
    with pytest.raises(ValueError, match="trial_frames"):
        build_reward_plan(
            RewardConditioningSettings("mouse", reward_images(), trial_frames=0), assignment
        )
    with pytest.raises(ValueError, match="reward_boundary"):
        build_reward_plan(
            RewardConditioningSettings("mouse", reward_images(), reward_boundary_frames=91), assignment
        )
