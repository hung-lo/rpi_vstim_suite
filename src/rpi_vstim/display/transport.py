"""Portable bounded sequence transport contract for the later native adapter."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Condition

from .sequence import FrameTransportAborted, FrameTransportBackpressure, FrameTransportClosed


@dataclass(frozen=True)
class DisplaySequenceMetadata:
    logical_frame_index: int
    event_id: str
    sequence_id: str
    asset_key: str
    photodiode_state: str
    payload_size: int
    producer_sequence: int


@dataclass(frozen=True)
class DisplaySequenceFrame:
    metadata: DisplaySequenceMetadata
    payload: bytes


class DisplaySequenceLease:
    def __init__(self, frame: DisplaySequenceFrame, acknowledge) -> None:
        self.frame = frame
        self._acknowledge = acknowledge
        self._acked = False

    def acknowledge(self) -> None:
        if not self._acked:
            self._acked = True
            self._acknowledge()


class InMemoryDisplaySequenceAdapter:
    """Bounded ownership/acknowledgement adapter used by integration tests."""

    def __init__(self, capacity: int = 2) -> None:
        if capacity <= 0:
            raise ValueError("sequence adapter capacity must be positive")
        self.capacity = capacity
        self._condition = Condition()
        self._ready: deque[tuple[int, DisplaySequenceFrame]] = deque()
        self._inflight: dict[int, DisplaySequenceFrame] = {}
        self._next_slot = 0
        self._next_sequence = 0
        self._closed = False
        self._aborted: str | None = None
        self._underruns = 0

    def publish(
        self,
        frame: DisplaySequenceFrame,
        *,
        timeout_s: float | None = None,
    ) -> None:
        if frame.metadata.payload_size != len(frame.payload):
            raise ValueError("payload_size does not match payload")
        if frame.metadata.producer_sequence != self._next_sequence:
            raise ValueError("producer sequence is not contiguous")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        with self._condition:
            while len(self._ready) + len(self._inflight) >= self.capacity:
                self._raise_if_closed()
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    raise FrameTransportBackpressure("display sequence is full")
                self._condition.wait(remaining)
            self._raise_if_closed()
            slot = self._next_slot
            self._next_slot += 1
            self._ready.append((slot, frame))
            self._next_sequence += 1
            self._condition.notify_all()

    def consume(self, *, timeout_s: float | None = None) -> DisplaySequenceLease | None:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        with self._condition:
            while not self._ready:
                if self._aborted is not None:
                    raise FrameTransportAborted(self._aborted)
                if self._closed:
                    return None
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    self._underruns += 1
                    raise TimeoutError("display sequence underrun")
                self._condition.wait(remaining)
            if self._aborted is not None:
                raise FrameTransportAborted(self._aborted)
            slot, frame = self._ready.popleft()
            self._inflight[slot] = frame
            return DisplaySequenceLease(frame, lambda: self._ack(slot))

    def finish(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def abort(self, reason: str) -> None:
        with self._condition:
            self._aborted = reason
            self._closed = True
            self._ready.clear()
            self._inflight.clear()
            self._condition.notify_all()

    def metrics(self) -> dict[str, int | bool | str | None]:
        with self._condition:
            return {
                "capacity": self.capacity,
                "ready": len(self._ready),
                "inflight": len(self._inflight),
                "occupancy": len(self._ready) + len(self._inflight),
                "underruns": self._underruns,
                "closed": self._closed,
                "aborted": self._aborted,
            }

    def _ack(self, slot: int) -> None:
        with self._condition:
            self._inflight.pop(slot, None)
            self._condition.notify_all()

    def _raise_if_closed(self) -> None:
        if self._aborted is not None:
            raise FrameTransportAborted(self._aborted)
        if self._closed:
            raise FrameTransportClosed("display sequence is closed")
