import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.lifecycle import LifecycleState
from rpi_vstim.core.runtime import run_simulated_session


def simulation_config(tmp_path, *, cameras=False, telemetry_required=False):
    values = {"paths": {"output_root": tmp_path}}
    if cameras:
        values["cameras"] = {
            "devices": [
                {"id": "face", "role": "face", "required": True, "device": "face-id"},
                {"id": "behavior", "role": "behavior", "device": "behavior-id"},
            ]
        }
    if telemetry_required:
        values["telemetry"] = {"enabled": True, "required": True, "host": "monitor"}
    return config_from_mapping(values)


def load_json(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_natural_simulation_covers_no_camera_and_two_local_cameras(tmp_path):
    plain = run_simulated_session(
        simulation_config(tmp_path), protocol_name="natural-images", session_id="plain", seed=17
    )
    with_cameras = run_simulated_session(
        simulation_config(tmp_path, cameras=True),
        protocol_name="natural-images",
        session_id="with-cameras",
        seed=17,
    )

    assert plain.ok and with_cameras.ok
    assert "camera_manifest.json" not in {path.name for path in plain.session.context.session_root.iterdir()}
    manifest = load_json(with_cameras.session.context.session_root, "camera_manifest.json")
    assert {camera["state"] for camera in manifest["cameras"]} == {"COMPLETED"}
    assert all("/dev/video" not in json.dumps(camera) for camera in manifest["cameras"])


def test_reward_simulation_replays_the_frozen_production_schedule(tmp_path):
    result = run_simulated_session(
        simulation_config(tmp_path),
        protocol_name="reward-conditioning",
        session_id="reward",
        seed=23,
    )
    plan = load_json(result.session.context.session_root, "plan.json")

    assert result.ok
    assert len(plan["events"]) == 500
    assert sum(event["metadata"]["reward_eligible"] for event in plan["events"]) == 220
    assert sum(event["metadata"]["reward_scheduled"] for event in plan["events"]) == 198


def test_simulation_failures_are_terminal_and_cleanup_is_safe(tmp_path):
    interrupted = run_simulated_session(
        simulation_config(tmp_path), session_id="interrupted", interrupt=True
    )
    required_camera = run_simulated_session(
        simulation_config(tmp_path, cameras=True),
        session_id="required-camera",
        camera_failures={"face"},
    )
    degraded = run_simulated_session(
        simulation_config(tmp_path, cameras=True),
        session_id="degraded",
        camera_failures={"behavior"},
        telemetry_failure=True,
    )
    required_telemetry = run_simulated_session(
        simulation_config(tmp_path, telemetry_required=True),
        session_id="required-telemetry",
        telemetry_failure=True,
    )

    assert interrupted.final_state == LifecycleState.INTERRUPTED
    assert required_camera.final_state == LifecycleState.FAILED
    assert required_telemetry.final_state == LifecycleState.FAILED
    assert degraded.ok and set(degraded.degraded) == {"camera", "telemetry"}
    for result in (interrupted, required_camera, degraded, required_telemetry):
        assert result.services.hardware.backend.outputs_safe
        assert result.services.display.config is None


def test_same_seed_replays_plan_and_telemetry_stays_bounded(tmp_path):
    first = run_simulated_session(
        simulation_config(tmp_path), session_id="replay-a", protocol_name="natural-images", seed=99
    )
    second = run_simulated_session(
        simulation_config(tmp_path), session_id="replay-b", protocol_name="natural-images", seed=99
    )
    first_root = first.session.context.session_root
    second_root = second.session.context.session_root

    assert (first_root / "plan.json").read_bytes() == (second_root / "plan.json").read_bytes()
    assert load_json(first_root, "session_manifest.json")["random_seeds"] == {"protocol": 99}
    assert load_json(first_root, "provenance.json")["repository_commit"]
    assert first.services.telemetry.messages.maxlen == 256
    assert len(first.services.telemetry.messages) <= 256
