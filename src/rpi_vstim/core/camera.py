from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .config import CamerasConfig


class CameraState(StrEnum):
    CONFIGURED = "CONFIGURED"
    READY = "READY"
    RECORDING = "RECORDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


class CameraStartupError(RuntimeError):
    pass


@dataclass
class FakeCameraStatus:
    camera_id: str
    role: str
    stable_device_identifier: str
    required: bool
    requested_start: bool = False
    requested_stop: bool = False
    state: CameraState = CameraState.CONFIGURED
    output_path: str = ""
    bytes_written: int = 0
    error: str | None = None


class FakeLocalCameraService:
    """Metadata-only local camera service; it never opens a device or writes frames."""

    def __init__(self, config: CamerasConfig, *, fail_ids: set[str] | None = None) -> None:
        self.config = config
        self.fail_ids = fail_ids or set()
        self.statuses = {
            device.id: FakeCameraStatus(
                device.id,
                device.role,
                device.stable_device_identifier,
                device.required,
            )
            for device in config.devices
        }
        self.session_root: Path | None = None

    @property
    def degraded(self) -> bool:
        return any(status.state == CameraState.DEGRADED for status in self.statuses.values())

    def start(self, session_root: Path) -> None:
        self.session_root = session_root
        for status in self.statuses.values():
            status.requested_start = True
            status.output_path = f"camera/{status.camera_id}/capture.fake.json"
            if status.camera_id in self.fail_ids:
                status.state = CameraState.FAILED if status.required else CameraState.DEGRADED
                status.error = "simulated camera startup failure"
                if status.required:
                    self._write_manifest()
                    raise CameraStartupError(status.camera_id)
                continue
            status.state = CameraState.READY
            status.state = CameraState.RECORDING
        self._write_manifest()

    def stop(self) -> None:
        for status in self.statuses.values():
            status.requested_stop = True
            if status.state == CameraState.RECORDING:
                status.state = CameraState.COMPLETED
        self._write_manifest()

    def manifest(self) -> list[dict[str, Any]]:
        return [asdict(status) | {"state": status.state.value} for status in self.statuses.values()]

    def _write_manifest(self) -> None:
        if self.session_root is None or not self.statuses:
            return
        from .session import atomic_write_json

        atomic_write_json(self.session_root / "camera_manifest.json", {"cameras": self.manifest()})

class CameraBackend:
    """Import-safe camera boundary; acquisition is intentionally not implemented."""

    def start(self) -> None:
        raise NotImplementedError("camera acquisition starts in a later phase")

    def stop(self) -> None:
        raise NotImplementedError("camera acquisition starts in a later phase")
