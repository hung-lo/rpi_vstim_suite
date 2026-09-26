"""Hardware-independent local camera supervision contracts."""

from .supervisor import (
    CameraCaptureSpec,
    CameraWorkerStatus,
    LocalCameraSupervisor,
    build_rpicam_command,
)

__all__ = [
    "CameraCaptureSpec",
    "CameraWorkerStatus",
    "LocalCameraSupervisor",
    "build_rpicam_command",
]
