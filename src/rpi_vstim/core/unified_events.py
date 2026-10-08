"""Bounded, clock-mapped JSONL events for integrated hardware sessions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Full, Queue
from threading import Event, Lock, Thread
from typing import Any


def _utc_text(utc_ns: int) -> str:
    seconds, nanoseconds = divmod(int(utc_ns), 1_000_000_000)
    value = datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=nanoseconds / 1_000
    )
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionClock:
    """One realtime/monotonic mapping used by every session event source."""

    session_id: str
    reference_utc_ns: int
    reference_monotonic_ns: int

    @classmethod
    def start(cls, session_id: str) -> SessionClock:
        # Sample both clocks together.  The monotonic clock remains authoritative
        # for ordering; realtime is derived from this single startup mapping.
        return cls(session_id, time.time_ns(), time.monotonic_ns())

    def fields(self, source_monotonic_ns: int | None = None) -> dict[str, Any]:
        monotonic = time.monotonic_ns() if source_monotonic_ns is None else int(source_monotonic_ns)
        utc = self.reference_utc_ns + (monotonic - self.reference_monotonic_ns)
        return {
            "utc_time": _utc_text(utc),
            "utc_ns": utc,
            "monotonic_ns": monotonic,
            "session_elapsed_s": (monotonic - self.reference_monotonic_ns) / 1_000_000_000,
        }

    def sync_fields(self) -> dict[str, int | str]:
        return {
            "clock_realtime": "CLOCK_REALTIME",
            "clock_monotonic": "CLOCK_MONOTONIC",
            "clock_realtime_ns": self.reference_utc_ns,
            "clock_monotonic_ns": self.reference_monotonic_ns,
            "mapping": "utc_ns = clock_realtime_ns + (event_monotonic_ns - clock_monotonic_ns)",
        }


class UnifiedEventHandoff:
    """Nonblocking event enqueue with one background JSONL writer."""

    def __init__(self, path: Path, *, capacity: int = 4096) -> None:
        if capacity <= 0:
            raise ValueError("event handoff capacity must be positive")
        self.path = Path(path)
        self.capacity = capacity
        self._queue: Queue[dict[str, Any] | None] = Queue(maxsize=capacity)
        self._stop = Event()
        self._close_lock = Lock()
        self._handle = self.path.open("w", encoding="utf-8")
        self._thread = Thread(target=self._run, name="rpi-vstim-unified-event-writer", daemon=True)
        self._thread.start()
        self.dropped_count = 0
        self.enqueue_count = 0
        self.error_count = 0
        self.written_count = 0
        self.high_water_mark = 0
        self.writer_error: str | None = None

    def publish(self, event: dict[str, Any]) -> bool:
        """Enqueue without waiting; safe for GPIO/KMS/camera callbacks."""
        try:
            self._queue.put_nowait(event)
        except Full:
            self.dropped_count += 1
            return False
        self.enqueue_count += 1
        self.high_water_mark = max(self.high_water_mark, self._queue.qsize())
        return True

    def publish_reliable(self, event: dict[str, Any]) -> None:
        """Drainable post-acquisition writes; timing callbacks must use publish()."""
        self._queue.put(event)
        self.enqueue_count += 1
        self.high_water_mark = max(self.high_water_mark, self._queue.qsize())

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                break
            try:
                self._handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                self._handle.flush()
                self.written_count += 1
            except Exception as exc:  # noqa: BLE001 — diagnostics must not reach timing sources
                self.error_count += 1
                self.writer_error = str(exc)

    def close(self, *, timeout_s: float = 5.0) -> dict[str, Any]:
        with self._close_lock:
            if self._stop.is_set():
                return self.diagnostics()
            self._stop.set()
            try:
                self._queue.put_nowait(None)
            except Full:
                # Drain is the writer's job; wait briefly for one slot, without
                # allowing shutdown to hang forever behind a broken sink.
                self._queue.put(None, timeout=timeout_s)
            self._thread.join(timeout=timeout_s)
            if self._thread.is_alive():
                raise RuntimeError("unified event writer did not stop before the cleanup deadline")
            try:
                self._handle.flush()
                os.fsync(self._handle.fileno())
                self._handle.close()
            finally:
                self._handle = None  # type: ignore[assignment]
            return self.diagnostics()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "capacity": self.capacity,
            "enqueue_count": self.enqueue_count,
            "written_count": self.written_count,
            "dropped_count": self.dropped_count,
            "error_count": self.error_count,
            "high_water_mark": self.high_water_mark,
            "event_enqueue_count": self.enqueue_count,
            "event_written_count": self.written_count,
            "event_drop_count": self.dropped_count,
            "event_writer_error_count": self.error_count,
            "event_queue_capacity": self.capacity,
            "event_queue_high_water_mark": self.high_water_mark,
            "writer_alive": self._thread.is_alive(),
            "writer_error": self.writer_error,
        }


class UnifiedEventStream:
    """Build timestamped event objects and hand them to a bounded writer."""

    def __init__(
        self,
        path: Path,
        *,
        session_id: str,
        clock: SessionClock,
        capacity: int = 4096,
    ) -> None:
        self.session_id = session_id
        self.clock = clock
        self.handoff = UnifiedEventHandoff(path, capacity=capacity)

    def emit(
        self,
        event: str,
        *,
        source_monotonic_ns: int | None = None,
        **fields: Any,
    ) -> bool:
        record = {
            "schema_version": 1,
            "event": event,
            "session_id": self.session_id,
            **self.clock.fields(source_monotonic_ns),
            **fields,
        }
        return self.handoff.publish(record)

    def close(self) -> dict[str, Any]:
        return self.handoff.close()

    def emit_reliable(
        self,
        event: str,
        *,
        source_monotonic_ns: int | None = None,
        **fields: Any,
    ) -> None:
        record = {
            "schema_version": 1,
            "event": event,
            "session_id": self.session_id,
            **self.clock.fields(source_monotonic_ns),
            **fields,
        }
        self.handoff.publish_reliable(record)

    def diagnostics(self) -> dict[str, Any]:
        return self.handoff.diagnostics()
