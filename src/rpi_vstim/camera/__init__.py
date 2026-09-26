"""Hardware-independent local camera supervision contracts."""

from .supervisor import (
    CameraCaptureSpec,
    CameraWorkerStatus,
    LocalCameraSupervisor,
    build_rpicam_command,
)
from .identity import (
    CameraIdentity,
    CameraResolutionReport,
    EnumeratedCamera,
    ResolvedCamera,
    parse_enumerated_cameras,
    resolve_camera_identities,
)

__all__ = [
    "CameraCaptureSpec",
    "CameraWorkerStatus",
    "LocalCameraSupervisor",
    "build_rpicam_command",
    "CameraIdentity",
    "CameraResolutionReport",
    "EnumeratedCamera",
    "ResolvedCamera",
    "parse_enumerated_cameras",
    "resolve_camera_identities",
]
