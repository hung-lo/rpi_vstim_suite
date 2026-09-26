from pathlib import Path
import json
import subprocess
import time

import pytest

from rpi_vstim.camera.supervisor import (
    BoundedCameraStatusChannel,
    CameraCaptureSpec,
    CameraStartupError,
    LocalCameraSupervisor,
    build_rpicam_command,
)
from rpi_vstim.core.camera import CameraState


class FakeProcess:
    def __init__(self, output_path: Path, *, exit_code: int | None = None) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"frame")
        self.returncode = exit_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def spec(camera_id: str, *, required: bool = False) -> CameraCaptureSpec:
    return CameraCaptureSpec(
        camera_id=camera_id,
        role=camera_id,
        stable_device_identifier=f"serial-{camera_id}",
        required=required,
        backend="test",
        command=("fake-camera", camera_id),
        output_extension="bin",
        startup_timeout_s=0.05,
        stop_timeout_s=0.05,
    )


def test_supervisor_starts_and_stops_independent_local_workers(tmp_path):
    processes = []

    def popen(command, **_kwargs):
        output_path = tmp_path / "session" / "camera" / command[1] / "capture.bin"
        process = FakeProcess(output_path)
        processes.append(process)
        return process

    supervisor = LocalCameraSupervisor(
        (spec("face", required=True), spec("behavior")),
        popen_factory=popen,
        status_capacity=8,
    )
    supervisor.start(tmp_path / "session")
    assert {status.state for status in supervisor.poll()} == {CameraState.RECORDING}
    statuses = supervisor.stop()
    assert {status.state for status in statuses} == {CameraState.COMPLETED}
    assert all(status.bytes_written == 5 for status in statuses)
    assert (tmp_path / "session" / "camera" / "face" / "capture.bin").is_file()
    assert len(supervisor.drain_status()) >= 4
    assert processes and all(process.terminated for process in processes)


def test_optional_worker_crash_degrades_without_stopping_other_worker(tmp_path):
    processes = {}

    def popen(command, **_kwargs):
        output_path = tmp_path / "session" / "camera" / command[1] / "capture.bin"
        process = FakeProcess(output_path)
        processes[command[1]] = process
        return process

    supervisor = LocalCameraSupervisor(
        (spec("face", required=True), spec("behavior")),
        popen_factory=popen,
    )
    supervisor.start(tmp_path / "session")
    processes["behavior"].returncode = 3
    statuses = {status.camera_id: status for status in supervisor.poll()}
    assert statuses["behavior"].state == CameraState.DEGRADED
    assert statuses["face"].state == CameraState.RECORDING
    supervisor.stop()
    assert processes["face"].terminated


def test_required_start_failure_cleans_up_previous_worker(tmp_path):
    processes = []

    def popen(command, **_kwargs):
        if command[1] == "behavior":
            raise OSError("simulated launch failure")
        output_path = tmp_path / "session" / "camera" / command[1] / "capture.bin"
        process = FakeProcess(output_path)
        processes.append(process)
        return process

    supervisor = LocalCameraSupervisor(
            (spec("face", required=True), spec("behavior", required=True)),
            popen_factory=popen,
        )
    with pytest.raises(CameraStartupError):
        supervisor.start(tmp_path / "session")
    assert processes[0].terminated
    manifest = json.loads((tmp_path / "session" / "camera_manifest.json").read_text())
    assert {camera["camera_id"] for camera in manifest["cameras"]} == {"face", "behavior"}


def test_status_channel_is_bounded():
    channel = BoundedCameraStatusChannel(2)
    for index in range(3):
        channel.publish({"index": index})
    assert channel.dropped == 1
    assert channel.drain() == ({"index": 1}, {"index": 2})


def test_rpicam_command_does_not_guess_transient_video_nodes(tmp_path):
    command = build_rpicam_command(
        CameraCaptureSpec(
            "face", "face", "usb-serial", True, "rpicam", (),
            requested_width_px=1280,
            requested_height_px=720,
            requested_fps=30.0,
            pixel_format_or_codec="h264",
        ),
        tmp_path / "capture.h264",
    )
    assert command[0] == "rpicam-vid"
    assert "/dev/video0" not in command
    assert "--width" in command and "1280" in command


def test_camera_stop_is_idempotent_and_records_monotonic_status_events(tmp_path):
    processes = []

    def popen(command, **_kwargs):
        output_path = tmp_path / "session" / "camera" / command[1] / "capture.bin"
        process = FakeProcess(output_path)
        processes.append(process)
        return process

    supervisor = LocalCameraSupervisor((spec("face", required=True),), popen_factory=popen)
    supervisor.start(tmp_path / "session")
    first = supervisor.stop()[0]
    second = supervisor.stop()[0]
    assert first.stop_monotonic_ns == second.stop_monotonic_ns
    assert all("timestamp_monotonic_ns" in event for event in supervisor.drain_status())


def test_camera_supervisor_rejects_repeated_active_start(tmp_path):
    def popen(command, **_kwargs):
        return FakeProcess(tmp_path / "session" / "camera" / command[1] / "capture.bin")

    supervisor = LocalCameraSupervisor((spec("face", required=True),), popen_factory=popen)
    supervisor.start(tmp_path / "session")
    with pytest.raises(RuntimeError, match="already active"):
        supervisor.start(tmp_path / "other")
    supervisor.stop()


class TimeoutProcess(FakeProcess):
    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("fake-camera", timeout)


class NeverReapsProcess(FakeProcess):
    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return None


def test_camera_stop_kills_after_timeout_and_does_not_claim_success(tmp_path):
    def popen(command, **_kwargs):
        return TimeoutProcess(tmp_path / "session" / "camera" / command[1] / "capture.bin")

    supervisor = LocalCameraSupervisor(
        (spec("face", required=True),), popen_factory=popen
    )
    supervisor.start(tmp_path / "session")
    status = supervisor.stop()[0]
    assert status.state == CameraState.FAILED
    assert status.verification_state == "output_nonempty_failed"


def test_camera_stop_marks_unreaped_process_failed(tmp_path):
    def popen(command, **_kwargs):
        return NeverReapsProcess(tmp_path / "session" / "camera" / command[1] / "capture.bin")

    supervisor = LocalCameraSupervisor(
        (spec("face", required=True),), popen_factory=popen
    )
    supervisor.start(tmp_path / "session")
    status = supervisor.stop()[0]
    assert status.state == CameraState.FAILED
    assert status.exit_reason == "camera process remained alive after kill"


def test_optional_camera_stall_degrades_and_records_last_growth(tmp_path):
    def popen(command, **_kwargs):
        return FakeProcess(tmp_path / "session" / "camera" / command[1] / "capture.bin")

    stalled = CameraCaptureSpec(**{**spec("behavior").__dict__, "stall_timeout_s": 0.001})
    supervisor = LocalCameraSupervisor((stalled,), popen_factory=popen)
    supervisor.start(tmp_path / "session")
    time.sleep(0.01)
    status = supervisor.poll()[0]
    assert status.state == CameraState.DEGRADED
    assert status.last_growth_bytes == 5
    supervisor.stop()
