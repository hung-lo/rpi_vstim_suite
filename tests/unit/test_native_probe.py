import json

import pytest

from rpi_vstim.core.config import DisplayConfig
from rpi_vstim.display.native_probe import (
    NativeKmsError,
    display_result_from_probe,
    run_native_probe,
)


def test_native_probe_wrapper_builds_bounded_command(monkeypatch, tmp_path):
    calls = {}

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "connector": "HDMI-A-1",
                "selected_mode": "1024x600@59.82",
                "pixel_format": "RGB565",
                "requested_frame_count": 2,
                "completed_frame_count": 2,
                "first_page_flip_monotonic_ns": 1,
                "last_page_flip_monotonic_ns": 2,
                "first_page_flip_realtime_ns": 3,
                "mean_vblank_interval_us": 16_683.0,
                "std_vblank_interval_us": 1.0,
                "maximum_vblank_interval_us": 16_684.0,
                "missed_vblank_count": 0,
                "aborted": False,
            }
        )
        stderr = ""

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("rpi_vstim.display.native_probe.subprocess.run", fake_run)
    result = run_native_probe(
        DisplayConfig(width_px=1024, height_px=600, refresh_hz=59.82),
        frames=2,
        binary=tmp_path / "kms_probe",
        color=(1, 2, 3),
        patch_corner="top_left",
        patch_size=12,
    )
    assert result["completed_frame_count"] == 2
    assert "--connector" in calls["command"]
    assert "top_left" in calls["command"]
    assert calls["kwargs"]["timeout"] >= 10.0
    assert "--probe-only" not in calls["command"]


def test_native_probe_can_request_read_only_mode(monkeypatch, tmp_path):
    class Completed:
        returncode = 0
        stdout = '{"connector": "HDMI-A-1", "modeset": false, "page_flip": false}'
        stderr = ""

    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return Completed()

    monkeypatch.setattr("rpi_vstim.display.native_probe.subprocess.run", fake_run)
    run_native_probe(
        DisplayConfig(width_px=1024, height_px=600, refresh_hz=59.82),
        frames=1,
        binary=tmp_path / "kms_probe",
        probe_only=True,
    )
    assert "--probe-only" in calls["command"]


def test_native_result_requires_contract_fields():
    with pytest.raises(NativeKmsError, match="missing fields"):
        display_result_from_probe({}, DisplayConfig(), sequence_id="test")


def test_native_probe_surfaces_process_failure(monkeypatch, tmp_path):
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        lambda command, **kwargs: Failed(),
    )
    with pytest.raises(NativeKmsError, match="permission denied"):
        run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe")
