"""Local camera discovery and supervision API."""

from .camera import (
    CameraCaptureSpec, CameraIdentity, LocalCameraSupervisor, enumerate_rpicam_cameras,
    resolve_camera_identities,
)

__all__ = [
    "CameraCaptureSpec", "CameraIdentity", "LocalCameraSupervisor", "enumerate_rpicam_cameras",
    "resolve_camera_identities",
]
