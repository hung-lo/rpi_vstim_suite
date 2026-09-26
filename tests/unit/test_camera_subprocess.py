import sys
from pathlib import Path

import pytest

from rpi_vstim.camera.supervisor import CameraCaptureSpec, CameraStartupError, LocalCameraSupervisor
from rpi_vstim.core.camera import CameraState


FIXTURE = Path(__file__).parents[1] / "fixtures" / "fake_camera_process.py"


def process_spec(tmp_path, mode: str, *, required: bool = True, startup_timeout_s: float = 0.2):
    output = tmp_path / "session" / "camera" / "face" / "capture.bin"
    return CameraCaptureSpec(
        "face",
        "face",
        "serial-face",
        required,
        "test",
        (
            sys.executable,
            str(FIXTURE),
            "--output",
            str(output),
            "--mode",
            mode,
            "--interval",
            "0.005",
        ),
        output_extension="bin",
        startup_timeout_s=startup_timeout_s,
        stop_timeout_s=0.1,
    )


def test_real_subprocess_camera_grows_and_stops(tmp_path):
    supervisor = LocalCameraSupervisor((process_spec(tmp_path, "normal"),))
    supervisor.start(tmp_path / "session")
    status = supervisor.stop()[0]
    assert status.state == CameraState.COMPLETED
    assert status.verification_state == "recorded"
    assert Path(tmp_path / "session" / "camera" / "face" / "stderr.log").exists() is False


def test_real_subprocess_camera_start_failure_is_explicit(tmp_path):
    supervisor = LocalCameraSupervisor((process_spec(tmp_path, "fail"),))
    with pytest.raises(CameraStartupError):
        supervisor.start(tmp_path / "session")
    assert (tmp_path / "session" / "camera_manifest.json").exists()


def test_real_subprocess_camera_no_growth_hits_startup_deadline(tmp_path):
    supervisor = LocalCameraSupervisor((process_spec(tmp_path, "no-growth", startup_timeout_s=0.03),))
    with pytest.raises(CameraStartupError):
        supervisor.start(tmp_path / "session")
    assert supervisor.manifest()[0]["state"] == "FAILED"


def test_real_subprocess_camera_growth_then_stall_is_failed_and_reaped(tmp_path):
    supervisor = LocalCameraSupervisor(
        (CameraCaptureSpec(**{**process_spec(tmp_path, "stall").__dict__, "stall_timeout_s": 0.03}),)
    )
    supervisor.start(tmp_path / "session")
    import time

    time.sleep(0.05)
    assert supervisor.poll()[0].state == CameraState.FAILED
    status = supervisor.stop()[0]
    assert status.verification_state == "output_nonempty_failed"


def test_real_subprocess_camera_ignore_terminate_requires_force_kill(tmp_path):
    supervisor = LocalCameraSupervisor((process_spec(tmp_path, "ignore-terminate"),))
    supervisor.start(tmp_path / "session")
    status = supervisor.stop()[0]
    assert status.state == CameraState.FAILED
    assert status.exit_reason == "forced_kill_after_stop_timeout"
