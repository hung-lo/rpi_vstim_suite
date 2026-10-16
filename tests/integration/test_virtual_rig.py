import json

from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.session import inspect_session
from rpi_vstim.core.virtual_rig import run_virtual_session


def virtual_config(tmp_path):
    return config_from_mapping(
        {
            "paths": {"output_root": tmp_path},
            "protocol": {"name": "natural-images", "version": "software-groundwork"},
            "cameras": {
                "devices": [
                    {"id": "face", "role": "face", "required": True, "device": "virtual-face"},
                    {"id": "behavior", "role": "behavior", "device": "virtual-behavior"},
                ]
            },
        }
    )


def test_virtual_rig_uses_sequence_adapter_subprocess_cameras_and_inspection(tmp_path):
    result = run_virtual_session(
        virtual_config(tmp_path),
        protocol_name="natural-images",
        session_id="success",
        seed=4,
    )
    root = result.session.context.session_root
    assert result.ok
    assert (root / "asset_manifest.json").is_file()
    assert all(camera["verification_state"] == "recorded" for camera in result.services.cameras.manifest())
    assert result.services.display.sequence.metrics()["underruns"] == 0
    report = inspect_session(root)
    assert report["status"] == "COMPLETE"
    assert report["required_files_present"]
    assert not report["corrupt_artifacts"]


def test_virtual_rig_required_camera_failure_is_terminal_and_inspectable(tmp_path):
    result = run_virtual_session(
        virtual_config(tmp_path),
        protocol_name="natural-images",
        session_id="failed",
        camera_failures={"face"},
    )
    root = result.session.context.session_root
    assert not result.ok
    assert result.final_state.value == "FAILED"
    manifest = json.loads((root / "camera_manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["cameras"][0]["state"] == "FAILED"
    assert inspect_session(root)["status"] == "FAILED"


def test_virtual_rig_force_kill_of_required_camera_is_not_complete(tmp_path):
    result = run_virtual_session(
        virtual_config(tmp_path),
        protocol_name="natural-images",
        session_id="camera-kill",
        camera_mode="ignore-terminate",
    )
    assert result.final_state.value == "CLEANUP_FAILED"
    assert inspect_session(result.session.context.session_root)["status"] == "CLEANUP_FAILED"


def test_virtual_rig_seeded_camera_failure_is_reproducible(tmp_path):
    result = run_virtual_session(
        virtual_config(tmp_path),
        protocol_name="natural-images",
        session_id="seeded-camera-failure",
        seed=1,
        camera_mode="seeded-failure",
    )
    assert result.final_state.value == "FAILED"
