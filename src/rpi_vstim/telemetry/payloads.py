from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .schema import OUTER_SCHEMA_VERSION, PAYLOAD_SCHEMA_VERSION

_RESERVED_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "type",
        "telemetry_schema_version",
        "session_id",
        "protocol",
        "protocol_version",
        "timestamp_utc",
        "lifecycle",
        "phase",
        "sequence_number",
        "trial_id",
        "trial",
        "stimulus",
        "image",
        "cameras",
        "camera_states",
        "camera_state",
        "counters",
        "error",
        "degraded",
        "session",
        "hardware",
        "integrity",
        "protocol_state",
        "capabilities",
        "elapsed_s",
        "eta_s",
        "control_schema_version",
    }
)


def aggregate_camera_state(cameras: list[dict[str, Any]]) -> str | None:
    """Return a conservative legacy summary; per-camera data remains authoritative."""
    if not cameras:
        return None
    states = [str(camera.get("state", "UNKNOWN")) for camera in cameras]
    if any(
        state == "FAILED" and camera.get("required", True)
        for state, camera in zip(states, cameras)
    ):
        return "FAILED"
    if any(state in {"FAILED", "DEGRADED"} for state in states):
        return "DEGRADED"
    if all(state == "COMPLETED" for state in states):
        return "COMPLETED"
    if all(state == "RECORDING" for state in states):
        return "RECORDING"
    return states[0]


@dataclass(frozen=True)
class TelemetryPayload:
    message_type: str
    protocol: str
    session_id: str
    sequence_number: int = 0


@dataclass(frozen=True)
class TelemetryMessage:
    """Protocol-neutral, JSON-safe message for the separate monitor consumer."""

    message_type: str
    session_id: str
    protocol: str
    lifecycle: str
    sequence_number: int = 0
    trial_id: str | None = None
    stimulus: str | None = None
    counters: dict[str, int] | None = None
    cameras: list[dict[str, Any]] | None = None
    error: str | None = None
    degraded: list[str] | None = None
    protocol_version: str | None = None
    timestamp_utc: str | None = None
    session: dict[str, Any] | None = None
    hardware: dict[str, Any] | None = None
    integrity: dict[str, Any] | None = None
    protocol_state: dict[str, Any] | None = None
    capabilities: dict[str, bool] | None = None
    elapsed_s: float | None = None
    eta_s: float | None = None
    control_schema_version: int | None = None

    def __post_init__(self) -> None:
        if self.message_type == "state":
            object.__setattr__(self, "message_type", "lifecycle")
        elif self.message_type == "trial_complete":
            object.__setattr__(self, "message_type", "trial")
        if self.timestamp_utc is None:
            object.__setattr__(
                self,
                "timestamp_utc",
                datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            )

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": OUTER_SCHEMA_VERSION,
            "type": {"lifecycle": "state", "trial": "trial_complete"}.get(
                self.message_type, self.message_type
            ),
            "telemetry_schema_version": PAYLOAD_SCHEMA_VERSION,
            "session_id": self.session_id,
            "protocol": self.protocol,
            "lifecycle": self.lifecycle,
            "phase": self.lifecycle,
            "sequence_number": self.sequence_number,
            "timestamp_utc": self.timestamp_utc,
        }
        if self.protocol_version is not None:
            value["protocol_version"] = self.protocol_version
        if self.timestamp_utc is not None:
            value["timestamp_utc"] = self.timestamp_utc
        for name in (
            "session", "hardware", "integrity", "protocol_state", "capabilities",
            "elapsed_s", "eta_s", "control_schema_version",
        ):
            item = getattr(self, name)
            if item is not None:
                value[name] = item
        if self.trial_id is not None:
            value["trial_id"] = self.trial_id
            value["trial"] = self.trial_id
        if self.stimulus is not None:
            value["stimulus"] = self.stimulus
            value["image"] = self.stimulus
        if self.cameras is not None:
            value["cameras"] = self.cameras
            value["camera_states"] = self.cameras
            value["camera_state"] = aggregate_camera_state(self.cameras)
        for name in ("counters", "error", "degraded"):
            item = getattr(self, name)
            if item is not None:
                value[name] = item
        if self.counters:
            collisions = _RESERVED_ENVELOPE_KEYS.intersection(self.counters)
            if collisions:
                names = ", ".join(sorted(collisions))
                raise ValueError(f"telemetry counter collides with reserved field(s): {names}")
            value.update(self.counters)
        return value

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> TelemetryMessage:
        value = json.loads(payload)
        if value.get("schema_version") != OUTER_SCHEMA_VERSION:
            raise ValueError("unsupported outer telemetry schema version")
        if value.get("telemetry_schema_version") != PAYLOAD_SCHEMA_VERSION:
            raise ValueError("unsupported telemetry payload schema version")
        required = ("type", "session_id", "protocol", "sequence_number", "timestamp_utc")
        if any(name not in value for name in required):
            raise ValueError("telemetry message is missing required fields")
        message_type = {"state": "lifecycle", "trial_complete": "trial"}.get(
            value["type"], value["type"]
        )
        return cls(
            message_type=message_type,
            session_id=value["session_id"],
            protocol=value["protocol"],
            lifecycle=value.get("lifecycle", value.get("phase", "")),
            sequence_number=value["sequence_number"],
            trial_id=value.get("trial_id", value.get("trial")),
            stimulus=value.get("stimulus", value.get("image")),
            counters=value.get("counters"),
            cameras=value.get("cameras", value.get("camera_states")),
            error=value.get("error"),
            degraded=value.get("degraded"),
            protocol_version=value.get("protocol_version"),
            timestamp_utc=value.get("timestamp_utc"),
            session=value.get("session"),
            hardware=value.get("hardware"),
            integrity=value.get("integrity"),
            protocol_state=value.get("protocol_state"),
            capabilities=value.get("capabilities"),
            elapsed_s=value.get("elapsed_s"),
            eta_s=value.get("eta_s"),
            control_schema_version=value.get("control_schema_version"),
        )
