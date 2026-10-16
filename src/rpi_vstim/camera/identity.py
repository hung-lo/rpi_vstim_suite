"""Stable camera identity resolution from live or fixture enumeration."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_RPICAM_CAMERA_LINE = re.compile(
    r"^\s*(\d+)\s*:\s*(\S+)\s+\[[^]]+\]\s+\(([^)]+)\)\s*$"
)


@dataclass(frozen=True)
class CameraIdentity:
    camera_id: str
    stable_device_identifier: str
    expected_family: str = ""


@dataclass(frozen=True)
class EnumeratedCamera:
    stable_device_identifier: str
    family: str
    runtime_selector: str
    topology: str

    def as_dict(self) -> dict[str, str]:
        return {
            "stable_device_identifier": self.stable_device_identifier,
            "family": self.family,
            "runtime_selector": self.runtime_selector,
            "topology": self.topology,
        }


@dataclass(frozen=True)
class ResolvedCamera:
    camera_id: str
    stable_device_identifier: str
    family: str
    runtime_selector: str
    topology: str

    def as_dict(self) -> dict[str, str]:
        return {
            "camera_id": self.camera_id,
            "stable_device_identifier": self.stable_device_identifier,
            "family": self.family,
            "runtime_selector": self.runtime_selector,
            "topology": self.topology,
        }


@dataclass(frozen=True)
class CameraResolutionReport:
    resolved: tuple[ResolvedCamera, ...]
    missing: tuple[str, ...]
    ambiguous: tuple[str, ...]
    mismatched_family: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing and not self.ambiguous and not self.mismatched_family

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "resolved": [camera.as_dict() for camera in self.resolved],
            "missing": list(self.missing),
            "ambiguous": list(self.ambiguous),
            "mismatched_family": list(self.mismatched_family),
        }


def parse_enumerated_cameras(value: str | Iterable[dict[str, Any]]) -> tuple[EnumeratedCamera, ...]:
    rows = json.loads(value) if isinstance(value, str) else value
    return tuple(
        EnumeratedCamera(
            str(row["stable_device_identifier"]),
            str(row["family"]),
            str(row["runtime_selector"]),
            str(row["topology"]),
        )
        for row in rows
    )


def parse_rpicam_camera_listing(value: str) -> tuple[EnumeratedCamera, ...]:
    cameras = []
    for line in value.splitlines():
        match = _RPICAM_CAMERA_LINE.match(line)
        if match is None:
            continue
        index, name, topology = match.groups()
        cameras.append(
            EnumeratedCamera(
                stable_device_identifier=topology,
                family=name.split("_", 1)[0],
                runtime_selector=index,
                topology=topology,
            )
        )
    if not cameras:
        raise ValueError("rpicam camera enumeration returned no cameras")
    if len({camera.runtime_selector for camera in cameras}) != len(cameras):
        raise ValueError("rpicam camera enumeration returned duplicate selectors")
    if len({camera.stable_device_identifier for camera in cameras}) != len(cameras):
        raise ValueError("rpicam camera enumeration returned duplicate stable identities")
    return tuple(cameras)


def enumerate_rpicam_cameras(
    command: str = "rpicam-hello", *, timeout_s: float = 5.0
) -> tuple[EnumeratedCamera, ...]:
    result = subprocess.run(
        (command, "--list-cameras"),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return parse_rpicam_camera_listing(f"{result.stdout}\n{result.stderr}")


def resolve_camera_identities(
    configured: Iterable[CameraIdentity],
    enumerated: Iterable[EnumeratedCamera],
) -> CameraResolutionReport:
    by_identity: dict[str, list[EnumeratedCamera]] = {}
    for camera in enumerated:
        by_identity.setdefault(camera.stable_device_identifier, []).append(camera)
    resolved: list[ResolvedCamera] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    mismatched: list[str] = []
    for wanted in configured:
        matches = by_identity.get(wanted.stable_device_identifier, [])
        if not matches:
            missing.append(wanted.camera_id)
            continue
        if len(matches) != 1:
            ambiguous.append(wanted.camera_id)
            continue
        camera = matches[0]
        if wanted.expected_family and wanted.expected_family != camera.family:
            mismatched.append(wanted.camera_id)
            continue
        resolved.append(
            ResolvedCamera(
                wanted.camera_id,
                camera.stable_device_identifier,
                camera.family,
                camera.runtime_selector,
                camera.topology,
            )
        )
    return CameraResolutionReport(tuple(resolved), tuple(missing), tuple(ambiguous), tuple(mismatched))
