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
    CameraPreviewEnvironment,
    CameraWorkerStatus,
    LocalCameraSupervisor,
    build_rpicam_command,
    resolve_camera_preview_environment,
)

__all__ = [
    "CameraCaptureSpec",
    "CameraIdentity",
    "CameraPreviewEnvironment",
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
    "resolve_camera_preview_environment",
]
