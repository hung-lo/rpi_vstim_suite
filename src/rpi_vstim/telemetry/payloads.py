from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .schema import OUTER_SCHEMA_VERSION, PAYLOAD_SCHEMA_VERSION


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

    def __post_init__(self) -> None:
        if self.timestamp_utc is None:
            object.__setattr__(
                self,
                "timestamp_utc",
                datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
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
        if self.trial_id is not None:
            value["trial_id"] = self.trial_id
            value["trial"] = self.trial_id
        if self.stimulus is not None:
            value["stimulus"] = self.stimulus
            value["image"] = self.stimulus
        if self.cameras is not None:
            value["cameras"] = self.cameras
            value["camera_states"] = self.cameras
            value["camera_state"] = self.cameras[0].get("state") if self.cameras else None
        for name in ("counters", "error", "degraded"):
            item = getattr(self, name)
            if item is not None:
                value[name] = item
        if self.counters:
            value.update(self.counters)
        return value

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> "TelemetryMessage":
        value = json.loads(payload)
        if value.get("schema_version") != OUTER_SCHEMA_VERSION:
            raise ValueError("unsupported outer telemetry schema version")
        if value.get("telemetry_schema_version") != PAYLOAD_SCHEMA_VERSION:
            raise ValueError("unsupported telemetry payload schema version")
        required = ("type", "session_id", "protocol", "sequence_number", "timestamp_utc")
        if any(name not in value for name in required):
            raise ValueError("telemetry message is missing required fields")
        message_type = {"state": "state", "trial_complete": "trial"}.get(
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
        )
