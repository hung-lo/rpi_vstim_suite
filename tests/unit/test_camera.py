import json

from rpi_vstim.core.camera import CameraState, FakeLocalCameraService
from rpi_vstim.core.config import config_from_mapping


def test_fake_cameras_have_independent_bounded_metadata_state(tmp_path):
    config = config_from_mapping(
        {
            "cameras": {
                "devices": [
                    {"id": "face", "role": "face", "required": True, "device": "face-id"},
                    {"id": "behavior", "role": "behavior", "device": "behavior-id"},
                ]
            }
        }
    )
    service = FakeLocalCameraService(config.cameras, fail_ids={"behavior"})
    service.start(tmp_path)
    service.stop()

    manifest = json.loads((tmp_path / "camera_manifest.json").read_text())
    by_id = {camera["camera_id"]: camera for camera in manifest["cameras"]}
    assert by_id["face"]["state"] == CameraState.COMPLETED
    assert by_id["behavior"]["state"] == CameraState.DEGRADED
    assert by_id["face"]["requested_start"] is True
    assert by_id["face"]["requested_stop"] is True
    assert "/dev/video" not in json.dumps(manifest)
