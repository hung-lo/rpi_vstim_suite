"""Record configured CSI cameras for a bounded interval with fast MP4 QC."""

import argparse
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from rpi_vstim.camera import (
    CameraCaptureSpec,
    CameraIdentity,
    LocalCameraSupervisor,
    build_rpicam_command,
    enumerate_rpicam_cameras,
    resolve_camera_identities,
)
from rpi_vstim.session import load_config, new_session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True, help="profile with two camera identities")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("seconds must be positive")
    config = load_config(args.config)
    if args.output_root:
        config = replace(config, paths=replace(config.paths, output_root=args.output_root))
    if len(config.cameras.devices) != 2:
        parser.error("configure exactly two cameras in the profile")
    try:
        report = resolve_camera_identities(
            (CameraIdentity(device.id, device.device, device.expected_family)
             for device in config.cameras.devices),
            enumerate_rpicam_cameras(),
        )
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        parser.error(f"camera discovery unavailable: {exc}")
    if not report.passed:
        parser.error(f"configured cameras unavailable: {report.as_dict()}")
    session = new_session(config, protocol_name="camera-example", session_id=f"camera-{time.time_ns()}")
    specs = []
    for device, camera in zip(config.cameras.devices, report.resolved, strict=True):
        base = CameraCaptureSpec(
            device.id, device.role, device.device, True, "rpicam", (),
            output_extension="mp4", requested_width_px=640,
            requested_height_px=480, requested_fps=30, resolved_camera=camera,
        )
        output = session.context.session_root / "camera" / device.id / "capture.mp4"
        specs.append(replace(base, command=build_rpicam_command(base, output, resolved_camera=camera)))
    supervisor = LocalCameraSupervisor(specs)
    status = "ABORTED"
    try:
        session.write_initial_outputs()
        supervisor.start(session.context.session_root)
        time.sleep(args.seconds)
        status = "COMPLETE"
    finally:
        cameras = supervisor.stop()
        if any(camera.exit_status != 0 or camera.verification_state != "recorded" for camera in cameras):
            status = "FAILED"
        if session.context.session_root.exists():
            session.update_status(status, lifecycle=status)
            session.close()
    print(f"{status}: {session.context.session_root}")
    if status != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
