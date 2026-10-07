import json
import struct
import subprocess
from pathlib import Path

import pytest

from rpi_vstim.core.config import DisplayConfig
from rpi_vstim.display.native_probe import (
    NativeKmsError,
    NativeKmsOwnershipError,
    display_result_from_probe,
    run_native_probe,
    run_native_sequence,
)
from rpi_vstim.display.transport import DisplaySequenceFrame, DisplaySequenceMetadata


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
        lease=True,
        frame_file=tmp_path / "pair.raw",
    )
    assert result["completed_frame_count"] == 2
    assert "--connector" in calls["command"]
    assert "top_left" in calls["command"]
    assert "--lease" in calls["command"]
    assert "--frame-file" in calls["command"]
    assert calls["kwargs"]["timeout"] >= 10.0
    assert "--probe-only" not in calls["command"]


def test_leased_probe_discovers_local_wayland_runtime_over_ssh(monkeypatch, tmp_path):
    calls = {}

    class Completed:
        returncode = 0
        stdout = '{"connector": "HDMI-A-1"}'
        stderr = ""

    monkeypatch.setenv("XDG_RUNTIME_DIR", "/foreign/runtime")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-9")
    monkeypatch.setattr("rpi_vstim.display.native_probe.os.getuid", lambda: 1000)
    monkeypatch.setattr(Path, "is_dir", lambda path: str(path) == "/run/user/1000")
    monkeypatch.setattr(Path, "is_socket", lambda path: str(path) == "/run/user/1000/wayland-0")
    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        lambda command, **kwargs: (calls.update(kwargs) or Completed()),
    )

    run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe", lease=True)

    assert calls["env"]["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert calls["env"]["WAYLAND_DISPLAY"] == "wayland-0"


def test_native_sequence_uses_one_stream_process_and_preserves_frame_metadata(monkeypatch, tmp_path):
    captured = bytearray()

    class Pipe:
        def write(self, data):
            captured.extend(data)
            return len(data)

        def close(self):
            return None

    class ReadPipe:
        def __init__(self, value):
            self.value = value

        def read(self):
            return self.value

    class Process:
        returncode = 0
        stdin = Pipe()
        stdout = ReadPipe(b'{"completed_frame_count": 2}')
        stderr = ReadPipe(b"")

        def poll(self):
            return None

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    calls = []
    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.Popen",
        lambda command, **kwargs: (calls.append((command, kwargs)) or Process()),
    )
    frames = (
        DisplaySequenceFrame(
            DisplaySequenceMetadata(0, "gray", "gray", "gray", "off", 8, 0),
            b"0" * 8,
        ),
        DisplaySequenceFrame(
            DisplaySequenceMetadata(1, "image", "image", "image", "on", 8, 1),
            b"1" * 8,
        ),
    )
    result = run_native_sequence(
        DisplayConfig(width_px=2, height_px=2, refresh_hz=59.82),
        frames,
        binary=tmp_path / "kms_probe",
        lease=True,
    )
    assert result["producer_frame_count"] == 2
    assert len(calls) == 1
    assert "--stream" in calls[0][0]
    assert "--lease" in calls[0][0]
    magic, version, frame_bytes = struct.unpack_from("<8sII", captured)
    assert magic == b"RPIKMS1\0"
    assert version == 1
    assert frame_bytes == 8
    first_index, first_producer, first_state, first_size = struct.unpack_from(
        "<QQBQ7x", captured, 16
    )
    assert (first_index, first_producer, first_state, first_size) == (0, 0, 0, 8)
    second_offset = 16 + 32 + 8
    second_index, second_producer, second_state, second_size = struct.unpack_from(
        "<QQBQ7x", captured, second_offset
    )
    assert (second_index, second_producer, second_state, second_size) == (1, 1, 1, 8)


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


def test_native_probe_classifies_compositor_ownership(monkeypatch, tmp_path):
    class Failed:
        returncode = 1
        stdout = ""
        stderr = (
            "DRM device is accessible but another session/compositor currently owns "
            "modesetting authority (DRM master)"
        )

    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        lambda command, **kwargs: Failed(),
    )
    with pytest.raises(NativeKmsOwnershipError, match="modesetting authority"):
        run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe")


@pytest.mark.parametrize(
    "detail",
    (
        "no usable CRTC for configured connector",
        "no usable primary plane supports RGB565",
        "unsupported pixel format RGB565",
        "timed out waiting for page-flip event",
        "page-flip run interrupted",
        "failed to restore original CRTC state",
    ),
)
def test_native_probe_preserves_injected_failure_diagnostics(monkeypatch, tmp_path, detail):
    class Failed:
        returncode = 1
        stdout = ""
        stderr = detail

    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        lambda command, **kwargs: Failed(),
    )
    with pytest.raises(NativeKmsError, match=detail):
        run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe")


def test_native_probe_reports_timeout_and_missing_binary(monkeypatch, tmp_path):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        timeout,
    )
    with pytest.raises(NativeKmsError, match="timed out"):
        run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe")

    def missing(command, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(
        "rpi_vstim.display.native_probe.subprocess.run",
        missing,
    )
    with pytest.raises(NativeKmsError, match="unavailable"):
        run_native_probe(DisplayConfig(), frames=1, binary=tmp_path / "kms_probe")


def test_native_result_preserves_timing_and_patch_diagnostics():
    payload = {
        "connector": "HDMI-A-1",
        "selected_mode": "1024x600@59.8214",
        "pixel_format": "RGB565",
        "requested_frame_count": 3,
        "completed_frame_count": 3,
        "first_page_flip_monotonic_ns": 1,
        "last_page_flip_monotonic_ns": 2,
        "first_page_flip_realtime_ns": 3,
        "mean_vblank_interval_us": 16_683.0,
        "std_vblank_interval_us": 1.0,
        "maximum_vblank_interval_us": 16_684.0,
        "p95_vblank_interval_us": 16_684.0,
        "p99_vblank_interval_us": 16_684.0,
        "intervals_outside_tolerance": 1,
        "estimated_dropped_frame_count": 1,
        "photodiode": {"frame_state": "even=on,odd=off"},
        "missed_vblank_count": 0,
        "aborted": False,
    }
    result = display_result_from_probe(
        payload,
        DisplayConfig(
            ownership="direct",
            stimulus_connector="HDMI-A-1",
            preview_connector="HDMI-A-2",
        ),
        sequence_id="test",
    )
    assert result.intervals_outside_tolerance == 1
    assert result.estimated_dropped_frame_count == 1
    assert result.photodiode_state == "even=on,odd=off"


def test_native_result_preserves_kernel_and_callback_timestamp_sources():
    payload = {
        "connector": "HDMI-A-2",
        "selected_mode": "1024x600@59.8214",
        "pixel_format": "RGB565",
        "requested_frame_count": 2,
        "completed_frame_count": 2,
        "first_page_flip_kernel_event_ns": 100,
        "last_page_flip_kernel_event_ns": 200,
        "first_page_flip_callback_monotonic_ns": 90,
        "last_page_flip_callback_monotonic_ns": 210,
        "first_page_flip_callback_realtime_ns": 300,
        "last_page_flip_callback_realtime_ns": 400,
        "timing_source": "kernel_event",
        "kernel_timestamp_clock": "monotonic",
        "mean_vblank_interval_us": 16_683.0,
        "std_vblank_interval_us": 1.0,
        "maximum_vblank_interval_us": 16_684.0,
        "missed_vblank_count": 0,
        "aborted": False,
        "photodiode": {
            "frame_state": "logical_frame_0=on,logical_frame_1=off,initial_modeset=off_preroll"
        },
    }
    result = display_result_from_probe(
        payload,
        DisplayConfig(
            ownership="lease",
            stimulus_connector="HDMI-A-2",
            preview_connector="HDMI-A-1",
        ),
        sequence_id="kernel",
    )
    assert result.first_page_flip_kernel_event_ns == 100
    assert result.last_page_flip_kernel_event_ns == 200
    assert result.first_page_flip_callback_monotonic_ns == 90
    assert result.last_page_flip_callback_realtime_ns == 400
    assert result.timing_source == "kernel_event"
    assert result.kernel_timestamp_clock == "monotonic"
    assert result.photodiode_state.startswith("logical_frame_0=on")
