from __future__ import annotations

from collections import deque
from dataclasses import asdict, is_dataclass
from typing import Any

class TelemetryPublisher:
    """Phase 00 null publisher: no socket is opened and no packet is sent."""

    def __init__(self) -> None:
        self.suppressed_count = 0

    def publish(self, payload: object) -> bool:
        self.suppressed_count += 1
        return False

    def close(self) -> None:
        return None


class InMemoryTelemetryPublisher(TelemetryPublisher):
    """Bounded telemetry sink for simulated sessions and integration tests."""

    def __init__(self, *, fail: bool = False, max_messages: int = 256) -> None:
        self.fail = fail
        self.messages: deque[dict[str, Any]] = deque(maxlen=max_messages)
        self.dropped_count = 0
        self.failed = False

    def publish(self, payload: object) -> bool:
        if self.fail:
            self.failed = True
            return False
        if len(self.messages) == self.messages.maxlen:
            self.dropped_count += 1
        if is_dataclass(payload):
            payload = asdict(payload)
        elif not isinstance(payload, dict):
            payload = {"payload": payload}
        self.messages.append(payload)
        return True
