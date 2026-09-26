"""Bounded producer/consumer boundary for future arbitrary frame sequences."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Condition, Event, Thread
from typing import Iterable, Iterator

from rpi_vstim.core.assets import AssetPreparer
from rpi_vstim.core.cache import BoundedCache
from rpi_vstim.core.plan import SessionPlan

from .renderer import ProductionFrameRenderer


@dataclass(frozen=True)
class PlannedFrame:
    frame_index: int
    event_id: str
    sequence_id: str
    asset_path: str
    asset_key: str
    photodiode_state: str
    rgb888: bytes


@dataclass(frozen=True)
class PreparedSequenceFrame:
    frame_index: int
    event_id: str
    sequence_id: str
    asset_path: str
    asset_key: str
    photodiode_state: str
    packed: bytes


class FrameTransportClosed(RuntimeError):
    pass


class FrameTransportAborted(FrameTransportClosed):
    pass


class FrameTransportBackpressure(TimeoutError):
    pass


@dataclass(frozen=True)
class PrefetchMetrics:
    capacity: int
    low_watermark: int
    high_watermark: int
    produced: int
    consumed: int
    peak_occupancy: int
    underruns: int
    producer_state: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "capacity": self.capacity,
            "low_watermark": self.low_watermark,
            "high_watermark": self.high_watermark,
            "produced": self.produced,
            "consumed": self.consumed,
            "peak_occupancy": self.peak_occupancy,
            "underruns": self.underruns,
            "producer_state": self.producer_state,
        }


class BoundedFrameTransport:
    """Portable bounded queue with explicit finish, abort, and backpressure."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("transport capacity must be positive")
        self.capacity = capacity
        self._queue: deque[PreparedSequenceFrame] = deque()
        self._condition = Condition()
        self._closed = False
        self._aborted: str | None = None

    def put(self, frame: PreparedSequenceFrame, *, timeout_s: float | None = None) -> None:
        deadline = self._deadline(timeout_s)
        with self._condition:
            while len(self._queue) >= self.capacity:
                self._raise_if_closed()
                remaining = self._remaining(deadline)
                if remaining == 0:
                    raise FrameTransportBackpressure("frame transport is full")
                self._condition.wait(remaining)
            self._raise_if_closed()
            self._queue.append(frame)
            self._condition.notify_all()

    def get(self, *, timeout_s: float | None = None) -> PreparedSequenceFrame | None:
        deadline = self._deadline(timeout_s)
        with self._condition:
            while not self._queue:
                if self._aborted is not None:
                    raise FrameTransportAborted(self._aborted)
                if self._closed:
                    return None
                remaining = self._remaining(deadline)
                if remaining == 0:
                    raise TimeoutError("no prepared frame available")
                self._condition.wait(remaining)
            if self._aborted is not None:
                raise FrameTransportAborted(self._aborted)
            frame = self._queue.popleft()
            self._condition.notify_all()
            return frame

    def finish(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def abort(self, reason: str) -> None:
        with self._condition:
            self._aborted = reason
            self._closed = True
            self._queue.clear()
            self._condition.notify_all()

    @property
    def aborted(self) -> str | None:
        return self._aborted

    def __len__(self) -> int:
        with self._condition:
            return len(self._queue)

    def wait_below(self, limit: int, *, timeout_s: float | None = None) -> bool:
        if not 0 < limit <= self.capacity:
            raise ValueError("limit must be between one and transport capacity")
        deadline = self._deadline(timeout_s)
        with self._condition:
            while len(self._queue) >= limit:
                self._raise_if_closed()
                remaining = self._remaining(deadline)
                if remaining == 0:
                    return False
                self._condition.wait(remaining)
            self._raise_if_closed()
            return True

    @staticmethod
    def _deadline(timeout_s: float | None) -> float | None:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        return None if timeout_s is None else time.monotonic() + timeout_s

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    def _raise_if_closed(self) -> None:
        if self._aborted is not None:
            raise FrameTransportAborted(self._aborted)
        if self._closed:
            raise FrameTransportClosed("frame transport is closed")

    def iter_frames(self) -> Iterator[PreparedSequenceFrame]:
        while True:
            frame = self.get()
            if frame is None:
                return
            yield frame


class PrefetchCoordinator:
    """Run one bounded producer with explicit watermarks and shutdown."""

    def __init__(
        self,
        frames: Iterable[PreparedSequenceFrame],
        transport: BoundedFrameTransport,
        *,
        low_watermark: int = 1,
        high_watermark: int | None = None,
    ) -> None:
        high = transport.capacity if high_watermark is None else high_watermark
        if not 0 <= low_watermark < high <= transport.capacity:
            raise ValueError("watermarks must satisfy 0 <= low < high <= capacity")
        self.frames = iter(frames)
        self.transport = transport
        self.low_watermark = low_watermark
        self.high_watermark = high
        self.produced = 0
        self.consumed = 0
        self.peak_occupancy = 0
        self.underruns = 0
        self.producer_state = "CREATED"
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("prefetch coordinator already started")
        self.producer_state = "RUNNING"
        self._thread = Thread(target=self._produce, name="rpi-vstim-prefetch", daemon=True)
        self._thread.start()

    def get(self, *, timeout_s: float | None = None) -> PreparedSequenceFrame | None:
        if self._thread is None:
            raise RuntimeError("prefetch coordinator is not started")
        try:
            frame = self.transport.get(timeout_s=timeout_s)
        except TimeoutError:
            if len(self.transport) <= self.low_watermark:
                self.underruns += 1
            raise
        if frame is None:
            return None
        self.consumed += 1
        return frame

    def stop(self, reason: str = "prefetch stopped") -> None:
        if self._thread is None:
            return
        self._stop.set()
        self.transport.abort(reason)
        self._thread.join(timeout=1.0)
        if self._thread.is_alive():
            self.producer_state = "FAILED"
            raise RuntimeError("prefetch producer did not stop")
        if self.producer_state == "RUNNING":
            self.producer_state = "STOPPED"

    def metrics(self) -> PrefetchMetrics:
        return PrefetchMetrics(
            self.transport.capacity,
            self.low_watermark,
            self.high_watermark,
            self.produced,
            self.consumed,
            self.peak_occupancy,
            self.underruns,
            self.producer_state,
        )

    def _produce(self) -> None:
        try:
            for frame in self.frames:
                if self._stop.is_set():
                    return
                self.transport.wait_below(self.high_watermark)
                self.transport.put(frame)
                self.produced += 1
                self.peak_occupancy = max(self.peak_occupancy, len(self.transport))
            self.transport.finish()
            self.producer_state = "EOF"
        except FrameTransportAborted:
            self.producer_state = "ABORTED"
        except BaseException as exc:
            self.producer_state = "FAILED"
            self.transport.abort(str(exc))


class NaturalImageFrameSource:
    """Map a natural-image plan to prepared frames without preloading the plan."""

    def __init__(
        self,
        preparer: AssetPreparer,
        renderer: ProductionFrameRenderer,
        *,
        gray_value: int = 127,
        gray_cache_size: int = 2,
    ) -> None:
        if not 0 <= gray_value <= 255:
            raise ValueError("gray_value must be between 0 and 255")
        self.preparer = preparer
        self.renderer = renderer
        self.gray_value = gray_value
        self._gray_cache = BoundedCache[str, bytes](
            gray_cache_size,
            size_of=len,
        )

    def _gray(self, asset_path: str) -> tuple[str, bytes]:
        key = (
            f"gray:{asset_path}:{self.gray_value}:"
            f"{self.renderer.width_px}x{self.renderer.height_px}"
        )
        value = self._gray_cache.get(key)
        if value is None:
            value = bytes((self.gray_value,)) * (
                self.renderer.width_px * self.renderer.height_px * 3
            )
            self._gray_cache.put(key, value)
        return key, value

    def planned_frames(self, plan: SessionPlan) -> Iterator[PlannedFrame]:
        for event in plan.events:
            asset_path = str(event.metadata.get("image", event.kind))
            if event.kind == "image":
                prepared = self.preparer.prepare(asset_path)
                asset_key, rgb888 = prepared.asset_key, prepared.rgb888
            else:
                asset_key, rgb888 = self._gray(asset_path)
            for offset in range(event.frame_count):
                yield PlannedFrame(
                    frame_index=event.planned_start_frame + offset,
                    event_id=event.event_id,
                    sequence_id=event.sequence_id or event.event_id,
                    asset_path=asset_path,
                    asset_key=asset_key,
                    photodiode_state=event.photodiode,
                    rgb888=rgb888,
                )

    def prepared_frames(self, plan: SessionPlan) -> Iterator[PreparedSequenceFrame]:
        for frame in self.planned_frames(plan):
            packed = self.renderer.prepare_payload(
                frame.rgb888,
                photodiode_state=frame.photodiode_state,
                asset_key=frame.asset_key,
            )
            yield PreparedSequenceFrame(
                frame_index=frame.frame_index,
                event_id=frame.event_id,
                sequence_id=frame.sequence_id,
                asset_path=frame.asset_path,
                asset_key=frame.asset_key,
                photodiode_state=frame.photodiode_state,
                packed=packed,
            )

    def metrics(self) -> dict[str, object]:
        return {
            "asset_cache": self.preparer.metrics(),
            "gray_cache": self._gray_cache.metrics(),
            "renderer_cache": {
                "items": len(self.renderer.cache),
                "max_items": self.renderer.cache.max_items,
                "hits": self.renderer.cache.hits,
                "misses": self.renderer.cache.misses,
                "memory_bytes": self.renderer.cache.memory_bytes,
            },
        }


def produce_frames(
    frames: Iterable[PreparedSequenceFrame],
    transport: BoundedFrameTransport,
    *,
    timeout_s: float | None = None,
) -> int:
    """Push a finite sequence with bounded backpressure and explicit EOF."""
    count = 0
    try:
        for frame in frames:
            transport.put(frame, timeout_s=timeout_s)
            count += 1
    except BaseException as exc:
        transport.abort(str(exc))
        raise
    transport.finish()
    return count
