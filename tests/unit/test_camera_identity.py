import json

import pytest

from rpi_vstim.camera.identity import (
    CameraIdentity,
    parse_enumerated_cameras,
    resolve_camera_identities,
)


def enumeration():
    return parse_enumerated_cameras(
        json.dumps(
            [
                {
                    "stable_device_identifier": "imx708-left",
                    "family": "imx708",
                    "runtime_selector": "camera=0",
                    "topology": "platform:10/i2c-1/port@0",
                },
                {
                    "stable_device_identifier": "imx708-right",
                    "family": "imx708",
                    "runtime_selector": "camera=1",
                    "topology": "platform:10/i2c-1/port@1",
                },
            ]
        )
    )


def test_camera_identity_resolution_distinguishes_two_same_family_cameras():
    report = resolve_camera_identities(
        (
            CameraIdentity("face", "imx708-left", "imx708"),
            CameraIdentity("behavior", "imx708-right", "imx708"),
        ),
        enumeration(),
    )
    assert report.passed
    assert [camera.runtime_selector for camera in report.resolved] == ["camera=0", "camera=1"]


@pytest.mark.parametrize("configured_field", ["missing", "ambiguous", "family"])
def test_camera_identity_resolution_fails_closed(configured_field):
    configured = CameraIdentity("face", "unknown", "imx708")
    available = enumeration()
    if configured_field == "ambiguous":
        available = available + (available[0],)
        configured = CameraIdentity("face", "imx708-left", "imx708")
    elif configured_field == "family":
        configured = CameraIdentity("face", "imx708-left", "imx219")
    report = resolve_camera_identities((configured,), available)
    assert not report.passed
    assert (
        report.missing
        or report.ambiguous
        or report.mismatched_family
    )
