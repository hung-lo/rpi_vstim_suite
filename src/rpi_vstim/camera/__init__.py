"""Hardware-independent local camera supervision contracts."""

from .identity import (
    CameraIdentity,
    CameraResolutionReport,
    EnumeratedCamera,
    ResolvedCamera,
    enumerate_rpicam_cameras,
    parse_enumerated_cameras,
    parse_rpicam_camera_listing,
    resolve_camera_identities,
)
from .supervisor import (
    CameraCaptureSpec,
    CameraWorkerStatus,
    LocalCameraSupervisor,
    build_rpicam_command,
)

__all__ = [
    "CameraCaptureSpec",
    "CameraIdentity",
    "CameraResolutionReport",
    "CameraWorkerStatus",
    "EnumeratedCamera",
    "LocalCameraSupervisor",
    "ResolvedCamera",
    "build_rpicam_command",
    "enumerate_rpicam_cameras",
    "parse_enumerated_cameras",
    "parse_rpicam_camera_listing",
    "resolve_camera_identities",
]
