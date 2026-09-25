from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schema import PAYLOAD_SCHEMA_VERSION


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

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "message_type": self.message_type,
            "session_id": self.session_id,
            "protocol": self.protocol,
            "lifecycle": self.lifecycle,
            "sequence_number": self.sequence_number,
        }
        for name in ("trial_id", "stimulus", "counters", "cameras", "error", "degraded"):
            item = getattr(self, name)
            if item is not None:
                value[name] = item
        return value

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> "TelemetryMessage":
        value = json.loads(payload)
        if value.get("schema_version") != PAYLOAD_SCHEMA_VERSION:
            raise ValueError("unsupported telemetry schema version")
        required = ("message_type", "session_id", "protocol", "lifecycle", "sequence_number")
        if any(name not in value for name in required):
            raise ValueError("telemetry message is missing required fields")
        return cls(
            message_type=value["message_type"],
            session_id=value["session_id"],
            protocol=value["protocol"],
            lifecycle=value["lifecycle"],
            sequence_number=value["sequence_number"],
            trial_id=value.get("trial_id"),
            stimulus=value.get("stimulus"),
            counters=value.get("counters"),
            cameras=value.get("cameras"),
            error=value.get("error"),
            degraded=value.get("degraded"),
        )
