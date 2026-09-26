"""Bounded producer/consumer boundary for future arbitrary frame sequences."""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass
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


class BoundedFrameTransport:
    """Portable bounded queue with explicit finish, abort, and backpressure."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("transport capacity must be positive")
        self.capacity = capacity
        self._queue: queue.Queue[PreparedSequenceFrame | object] = queue.Queue(maxsize=capacity)
        self._closed = False
        self._aborted: str | None = None

    def put(self, frame: PreparedSequenceFrame, *, timeout_s: float | None = None) -> None:
        if self._closed:
            if self._aborted is not None:
                raise FrameTransportAborted(self._aborted)
            raise FrameTransportClosed("frame transport is closed")
        try:
            self._queue.put(frame, timeout=timeout_s)
        except queue.Full as exc:
            raise FrameTransportBackpressure("frame transport is full") from exc

    def get(self, *, timeout_s: float | None = None) -> PreparedSequenceFrame | None:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            if self._closed and self._queue.empty():
                return None
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty as exc:
                if self._closed:
                    return None
                raise TimeoutError("no prepared frame available") from exc
            return item

    def finish(self) -> None:
        self._closed = True

    def abort(self, reason: str) -> None:
        self._aborted = reason
        self._closed = True

    @property
    def aborted(self) -> str | None:
        return self._aborted

    def __len__(self) -> int:
        return self._queue.qsize()

    def iter_frames(self) -> Iterator[PreparedSequenceFrame]:
        while True:
            frame = self.get()
            if frame is None:
                return
            yield frame


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
            rendered = self.renderer.prepare(
                frame.frame_index,
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
                packed=bytes(rendered.data),
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
