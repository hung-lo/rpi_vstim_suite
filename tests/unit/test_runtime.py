import csv
import json
import threading
import time
from dataclasses import replace

import pytest

from rpi_vstim.core.config import Config, config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState
from rpi_vstim.core.plan import PlannedEvent, SessionPlan
from rpi_vstim.core.runtime import build_simulated_services, run_simulated_session
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.hardware.calibration import (
    CalibrationCondition,
    CalibrationProfile,
    write_profile,
)
from rpi_vstim.hardware.operator_control import send_manual_bait


def simulation_config(tmp_path, *, cameras=True):
    values = {"paths": {"output_root": tmp_path}}
    if cameras:
        values["cameras"] = {
            "devices": [
                {"id": "face", "role": "face", "required": True, "device": "face-serial"},
                {"id": "behavior", "role": "behavior", "device": "behavior-serial"},
            ]
        }
    return config_from_mapping(values)


def test_simulated_session_completes_and_writes_events(tmp_path):
    result = run_simulated_session(simulation_config(tmp_path), session_id="complete", seed=7)

    assert result.ok
    root = tmp_path / "complete"
    manifest = json.loads((root / "session_manifest.json").read_text())
    assert manifest["status"] == "COMPLETE"
    assert manifest["random_seeds"] == {"protocol": 7}
    assert (root / "events.csv").read_text().count("SESSION_FINISHED") == 1
    assert (root / "preflight_report.json").is_file()
    assert (root / "cache_manifest.json").is_file()
    assert (root / "resource_summary.json").is_file()
    display_summary = json.loads((root / "display_results.json").read_text())
    assert display_summary["record_count"] > 0
    assert json.loads((root / "display_results.jsonl").read_text().splitlines()[0])
    assert json.loads((root / "final_status.json").read_text())["status"] == "COMPLETE"
    cameras = json.loads((root / "camera_manifest.json").read_text())
    assert {camera["state"] for camera in cameras["cameras"]} == {"COMPLETED"}


def test_interruption_and_protocol_failure_are_terminal_and_safe(tmp_path):
    interrupted = run_simulated_session(
        simulation_config(tmp_path), session_id="interrupted", interrupt=True
    )
    failed = run_simulated_session(
        simulation_config(tmp_path), session_id="failed", protocol_failure=True
    )

    assert interrupted.final_state == LifecycleState.INTERRUPTED
    assert failed.final_state == LifecycleState.FAILED
    assert interrupted.services.hardware.backend.outputs_safe
    assert failed.services.hardware.backend.outputs_safe


def test_required_camera_failure_fails_without_touching_stimulus_outputs(tmp_path):
    result = run_simulated_session(
        simulation_config(tmp_path), session_id="camera-failed", camera_failures={"face"}
    )

    assert result.final_state == LifecycleState.FAILED
    assert (tmp_path / "camera-failed" / "session_manifest.json").is_file()
    assert (tmp_path / "camera-failed" / "resolved_config.json").is_file()
    assert result.services.hardware.backend.outputs_safe


def test_optional_camera_and_telemetry_failures_degrade(tmp_path):
    result = run_simulated_session(
        simulation_config(tmp_path),
        session_id="degraded",
        camera_failures={"behavior"},
        telemetry_failure=True,
    )

    assert result.ok
    assert set(result.degraded) == {"camera", "telemetry"}


def test_simulated_session_without_cameras(tmp_path):
    result = run_simulated_session(
        simulation_config(tmp_path, cameras=False), session_id="no-cameras"
    )
    assert result.ok


def test_session_composes_one_reward_owner_for_task_and_remote_bait(tmp_path):
    profile_path = tmp_path / "calibration.json"
    write_profile(
        CalibrationProfile.create(
            calibration_id="integration-calibration",
            rig_id="simulated-rig",
            conditions=(
                CalibrationCondition.measured(10, 10, 0, 0.02),
                CalibrationCondition.measured(20, 10, 0, 0.04),
            ),
        ),
        profile_path,
    )
    base = Config()
    config = replace(
        base,
        hardware=replace(
            base.hardware,
            reward_active_level=1,
            reward_open_duration_ms=1.0,
            reward_calibration_profile=profile_path,
        ),
        operator_controls=replace(
            base.operator_controls,
            manual_bait_enabled=True,
            bait_button_enabled=False,
            bait_reward_ul=2.0,
        ),
        paths=replace(
            base.paths,
            output_root=tmp_path / "sessions",
            operator_control_socket=tmp_path / "operator.sock",
        ),
    )
    plan = SessionPlan(
        "integration",
        1,
        (
            PlannedEvent(
                "reward-event",
                "rewarded-image",
                1,
                trial_id="trial-1",
                sequence_id="seq-1",
                metadata={"reward_scheduled": True, "image": "image.png"},
            ),
            PlannedEvent("end", "gray", 1, phase="POST"),
        ),
    )

    class SlowDisplay(FakeDisplayBackend):
        def present_color(self, rgb, *, frames):
            time.sleep(0.05)
            return super().present_color(rgb, frames=frames)

    services = build_simulated_services(config)
    services.display = SlowDisplay()
    result_holder = {}
    def run_session():
        try:
            result_holder["result"] = run_simulated_session(
                config, plan=plan, session_id="integrated", services=services
            )
        except BaseException as exc:  # noqa: BLE001 — surface sandbox limitations below
            result_holder["error"] = exc

    thread = threading.Thread(target=run_session, daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    while not config.paths.operator_control_socket.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not config.paths.operator_control_socket.exists():
        thread.join(timeout=3)
        if isinstance(result_holder.get("error"), PermissionError):
            pytest.skip("sandbox disallows AF_UNIX filesystem sockets")
        if result_holder.get("error") is not None:
            raise result_holder["error"]
        if "Operation not permitted" in str(getattr(result_holder.get("result"), "error", "")):
            pytest.skip("sandbox disallows AF_UNIX filesystem sockets")
        pytest.fail("active session did not expose the operator endpoint")
    response = send_manual_bait(config.paths.operator_control_socket)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert response["ok"] is True
    result = result_holder["result"]
    assert result.ok
    arbiter = result.services.reward_arbiter
    controls = result.services.operator_controls
    assert controls is not None
    assert controls._arbiter is arbiter
    assert controls._backend is None
    assert len(arbiter.controller._backend.transitions) == 4
    with (tmp_path / "sessions" / "integrated" / "events.csv").open(newline="") as handle:
        event_rows = list(csv.DictReader(handle))
    reward_rows = [row for row in event_rows if row["event"] == "reward_command"]
    assert len(reward_rows) == 2
    assert any("manual-bait-000001" in row["detail"] for row in reward_rows)
    provenance = json.loads(
        (tmp_path / "sessions" / "integrated" / "provenance.json").read_text()
    )
    assert provenance["reward_event_handoff"]["dropped_count"] == 0
    assert provenance["reward_event_handoff"]["error_count"] == 0
    assert not config.paths.operator_control_socket.exists()
