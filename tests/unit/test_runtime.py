import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState
from rpi_vstim.core.runtime import run_simulated_session


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
    assert json.loads((root / "display_results.json").read_text())["results"]
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
