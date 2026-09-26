"""Hardware-worker messages that are safe to exercise without GPIO access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from queue import Full, Queue


class HardwareCommandKind(StrEnum):
    SAFE = "SAFE"
    SHUTDOWN = "SHUTDOWN"
    REWARD = "REWARD"
    SUCTION = "SUCTION"


@dataclass(frozen=True)
class HardwareCommand:
    command_id: str
    kind: HardwareCommandKind
    volume_ul: int = 0

    def __post_init__(self) -> None:
        if not self.command_id or not self.command_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("hardware command_id must be non-empty and identifier-safe")
        if self.volume_ul < 0:
            raise ValueError("hardware volume must be non-negative")


@dataclass(frozen=True)
class HardwareEvent:
    command_id: str
    event: str
    outputs_safe: bool
    delivered_ul: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "event": self.event,
            "outputs_safe": self.outputs_safe,
            "delivered_ul": self.delivered_ul,
        }


class BoundedHardwareCommandQueue:
    """Small queue contract; production IPC can replace the transport later."""

    def __init__(self, capacity: int = 64) -> None:
        if capacity <= 0:
            raise ValueError("hardware command capacity must be positive")
        self._queue: Queue[HardwareCommand] = Queue(maxsize=capacity)

    def put(self, command: HardwareCommand) -> None:
        try:
            self._queue.put_nowait(command)
        except Full as exc:
            raise BufferError("hardware command queue is full") from exc

    def get(self) -> HardwareCommand:
        return self._queue.get_nowait()

    def __len__(self) -> int:
        return self._queue.qsize()
