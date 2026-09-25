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

    def __init__(
        self, *, fail: bool = False, fail_after: int | None = None, max_messages: int = 256
    ) -> None:
        self.fail = fail
        self.fail_after = fail_after
        self.publish_count = 0
        self.messages: deque[dict[str, Any]] = deque(maxlen=max_messages)
        self.dropped_count = 0
        self.failed = False

    def publish(self, payload: object) -> bool:
        if self.fail or (self.fail_after is not None and self.publish_count >= self.fail_after):
            self.failed = True
            return False
        self.publish_count += 1
        if len(self.messages) == self.messages.maxlen:
            self.dropped_count += 1
        if hasattr(payload, "as_dict"):
            payload = payload.as_dict()
        elif is_dataclass(payload):
            payload = asdict(payload)
        elif not isinstance(payload, dict):
            payload = {"payload": payload}
        self.messages.append(payload)
        return True
