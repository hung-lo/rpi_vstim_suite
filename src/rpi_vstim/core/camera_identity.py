"""Stable camera identity resolution independent of transient video nodes."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CamerasConfig


class CameraIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class CameraIdentity:
    model: str
    topology: str
    sensor_path: str
    runtime_devices: tuple[str, ...] = ()

    @property
    def stable_keys(self) -> frozenset[str]:
        return frozenset((self.topology, self.sensor_path))


def resolve_camera_identities(
    config: CamerasConfig,
    identities: tuple[CameraIdentity, ...],
) -> dict[str, CameraIdentity]:
    """Resolve configured devices by stable key, never by `/dev/videoN`."""
    resolved: dict[str, CameraIdentity] = {}
    for device in config.devices:
        if not device.device:
            if device.required:
                raise CameraIdentityError(f"required camera lacks a stable identity: {device.id}")
            continue
        matches = [identity for identity in identities if device.device in identity.stable_keys]
        if not matches:
            if device.required:
                raise CameraIdentityError(f"required camera identity is missing: {device.id}")
            continue
        if len(matches) > 1:
            raise CameraIdentityError(f"camera identity is ambiguous: {device.id}")
        identity = matches[0]
        if identity in resolved.values():
            raise CameraIdentityError(f"camera identity is bound more than once: {device.device}")
        resolved[device.id] = identity
    return resolved
