from __future__ import annotations


class TelemetryPublisher:
    """Phase 00 null publisher: no socket is opened and no packet is sent."""

    def __init__(self) -> None:
        self.suppressed_count = 0

    def publish(self, payload: object) -> bool:
        self.suppressed_count += 1
        return False

    def close(self) -> None:
        return None

