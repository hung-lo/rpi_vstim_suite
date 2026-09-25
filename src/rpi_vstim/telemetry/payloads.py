from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelemetryPayload:
    message_type: str
    protocol: str
    session_id: str
    sequence_number: int = 0

