import json

import pytest

from rpi_vstim.camera.identity import (
    CameraIdentity,
    parse_enumerated_cameras,
    parse_rpicam_camera_listing,
    resolve_camera_identities,
)


def enumeration():
    return parse_enumerated_cameras(
        json.dumps(
            [
                {
                    "stable_device_identifier": "imx708-left",
                    "family": "imx708",
                    "runtime_selector": "0",
                    "topology": "platform:10/i2c-1/port@0",
                },
                {
                    "stable_device_identifier": "imx708-right",
                    "family": "imx708",
                    "runtime_selector": "1",
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
    assert [camera.runtime_selector for camera in report.resolved] == ["0", "1"]


def test_rpicam_listing_resolves_topology_and_numeric_selector():
    cameras = parse_rpicam_camera_listing(
        """Available cameras
-----------------
0 : imx708_noir [4608x2592 10-bit RGGB] (/base/axi/i2c@88000/imx708@1a)
1 : imx708_wide_noir [4608x2592 10-bit RGGB] (/base/axi/i2c@80000/imx708@1a)
"""
    )
    assert [(camera.family, camera.runtime_selector) for camera in cameras] == [
        ("imx708", "0"),
        ("imx708", "1"),
    ]
    assert cameras[0].stable_device_identifier == cameras[0].topology


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
