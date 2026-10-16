import pytest

from rpi_vstim.core.camera_identity import (
    CameraIdentity,
    CameraIdentityError,
    resolve_camera_identities,
)
from rpi_vstim.core.config import CameraDeviceConfig, CamerasConfig
from rpi_vstim.core.storage import inspect_storage


def test_storage_inspection_distinguishes_absent_and_unmounted(tmp_path):
    absent = inspect_storage(tmp_path / "missing")
    assert absent.status == "absent"
    root = inspect_storage(tmp_path)
    assert root.status == "not_mounted"
    assert root.free_bytes is not None


def test_camera_resolution_ignores_transient_node_order():
    identities = (
        CameraIdentity("imx708_wide_noir", "platform:wide", "/i2c@80000/imx708@1a", ("/dev/video0",)),
        CameraIdentity("imx708_noir", "platform:noir", "/i2c@88000/imx708@1a", ("/dev/video8",)),
    )
    config = CamerasConfig(
        devices=(
            CameraDeviceConfig("face", "face", True, "rpicam", "platform:noir"),
            CameraDeviceConfig("behavior", "behavior", True, "rpicam", "platform:wide"),
        )
    )
    resolved = resolve_camera_identities(config, identities)
    assert resolved["face"].model == "imx708_noir"
    assert resolved["behavior"].model == "imx708_wide_noir"


def test_camera_resolution_rejects_missing_and_duplicate_stable_identity():
    identity = CameraIdentity("camera", "platform:one", "/sensor/one")
    with pytest.raises(CameraIdentityError, match="missing"):
        resolve_camera_identities(
            CamerasConfig(devices=(CameraDeviceConfig("required", "face", True, device="platform:missing"),)),
            (identity,),
        )
    config = CamerasConfig(
        devices=(
            CameraDeviceConfig("one", "one", True, device="platform:one"),
            CameraDeviceConfig("two", "two", True, device="platform:one"),
        )
    )
    with pytest.raises(CameraIdentityError, match="bound more than once"):
        resolve_camera_identities(config, (identity,))
