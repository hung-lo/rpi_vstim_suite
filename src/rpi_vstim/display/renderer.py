"""Bounded preparation of production scanout frames."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .photodiode import PhotodiodePatch, patch_bounds, patch_value

_FORMATS = {"RGB565": 2, "XRGB8888": 4}


class BoundedFrameCache:
    """Small LRU cache whose size is explicit and testable."""

    def __init__(self, max_items: int) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        self.max_items = max_items
        self._items: OrderedDict[Any, bytes] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> bytes | None:
        value = self._items.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        self._items.move_to_end(key)
        return value

    def put(self, key: Any, value: bytes) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def memory_bytes(self) -> int:
        return sum(len(value) for value in self._items.values())


@dataclass(frozen=True)
class RenderedFrame:
    frame_index: int
    width_px: int
    height_px: int
    pixel_format: str
    stride_bytes: int
    photodiode_state: str
    data: memoryview


def _format_bpp(pixel_format: str) -> int:
    try:
        return _FORMATS[pixel_format]
    except KeyError as exc:
        raise ValueError(f"unsupported pixel format: {pixel_format}") from exc


def convert_rgb888_frame(
    rgb888: bytes | bytearray | memoryview,
    width_px: int,
    height_px: int,
    pixel_format: str,
    *,
    source_stride: int | None = None,
    destination_stride: int | None = None,
) -> bytearray:
    """Convert one tightly or explicitly strided RGB888 frame."""
    if width_px <= 0 or height_px <= 0:
        raise ValueError("frame dimensions must be positive")
    bpp = _format_bpp(pixel_format)
    minimum_source_stride = width_px * 3
    source_stride = minimum_source_stride if source_stride is None else source_stride
    destination_stride = width_px * bpp if destination_stride is None else destination_stride
    if source_stride < minimum_source_stride:
        raise ValueError("source stride is too small for RGB888 frame")
    if destination_stride < width_px * bpp:
        raise ValueError("destination stride is too small for pixel format")
    source = memoryview(rgb888).cast("B")
    if len(source) < source_stride * height_px:
        raise ValueError("RGB888 frame is shorter than its declared stride")
    destination = bytearray(destination_stride * height_px)
    for y in range(height_px):
        source_row = y * source_stride
        destination_row = y * destination_stride
        for x in range(width_px):
            source_index = source_row + x * 3
            red, green, blue = source[source_index:source_index + 3]
            destination_index = destination_row + x * bpp
            if pixel_format == "RGB565":
                value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
                destination[destination_index] = value & 0xFF
                destination[destination_index + 1] = value >> 8
            else:
                destination[destination_index] = blue
                destination[destination_index + 1] = green
                destination[destination_index + 2] = red
                destination[destination_index + 3] = 0
    return destination


def apply_photodiode_patch(
    frame: bytearray,
    width_px: int,
    height_px: int,
    pixel_format: str,
    stride_bytes: int,
    patch: PhotodiodePatch,
    state: str,
) -> None:
    """Apply the patch to the same prepared buffer submitted for a frame."""
    bpp = _format_bpp(pixel_format)
    if stride_bytes < width_px * bpp or len(frame) < stride_bytes * height_px:
        raise ValueError("frame stride or storage is too small")
    x0, y0, size, _ = patch_bounds(width_px, height_px, patch)
    value = patch_value(patch, state)
    if pixel_format == "RGB565":
        packed = ((value >> 3) << 11) | ((value >> 2) << 5) | (value >> 3)
        pixel = bytes((packed & 0xFF, packed >> 8))
    else:
        pixel = bytes((value, value, value, 0))
    for y in range(y0, y0 + size):
        row = y * stride_bytes
        for x in range(x0, x0 + size):
            start = row + x * bpp
            frame[start:start + bpp] = pixel


def photodiode_state_for_frame(frame_index: int, *, on_even: bool = True) -> str:
    if frame_index < 0:
        raise ValueError("frame_index must be non-negative")
    return "on" if ((frame_index % 2 == 0) == on_even) else "off"


class ProductionFrameRenderer:
    """Prepare deterministic frames with two reusable scanout buffers."""

    def __init__(
        self,
        width_px: int,
        height_px: int,
        pixel_format: str,
        *,
        photodiode: PhotodiodePatch | None = None,
        cache_size: int = 8,
    ) -> None:
        bpp = _format_bpp(pixel_format)
        if width_px <= 0 or height_px <= 0:
            raise ValueError("frame dimensions must be positive")
        self.width_px = width_px
        self.height_px = height_px
        self.pixel_format = pixel_format
        self.stride_bytes = width_px * bpp
        self.photodiode = photodiode
        self.cache = BoundedFrameCache(cache_size)
        buffer_size = self.stride_bytes * height_px
        self._buffers = (bytearray(buffer_size), bytearray(buffer_size))

    @property
    def scanout_buffer_bytes(self) -> int:
        return sum(len(buffer) for buffer in self._buffers)

    @property
    def estimated_memory_bytes(self) -> int:
        return self.scanout_buffer_bytes + self.cache.memory_bytes

    def prepare(
        self,
        frame_index: int,
        rgb888: bytes | bytearray | memoryview,
        *,
        photodiode_state: str | None = None,
    ) -> RenderedFrame:
        if frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        photodiode_state = (
            photodiode_state_for_frame(frame_index)
            if photodiode_state is None
            else photodiode_state
        )
        if photodiode_state not in {"on", "off"}:
            raise ValueError("photodiode_state must be 'on' or 'off'")
        key = (frame_index, photodiode_state)
        packed = self.cache.get(key)
        if packed is None:
            prepared = convert_rgb888_frame(
                rgb888,
                self.width_px,
                self.height_px,
                self.pixel_format,
                destination_stride=self.stride_bytes,
            )
            if self.photodiode is not None:
                apply_photodiode_patch(
                    prepared,
                    self.width_px,
                    self.height_px,
                    self.pixel_format,
                    self.stride_bytes,
                    self.photodiode,
                    photodiode_state,
                )
            packed = bytes(prepared)
            self.cache.put(key, packed)
        target = self._buffers[frame_index % 2]
        target[:] = packed
        return RenderedFrame(
            frame_index,
            self.width_px,
            self.height_px,
            self.pixel_format,
            self.stride_bytes,
            photodiode_state,
            memoryview(target),
        )

    def prepare_pair(
        self,
        rgb888_on: bytes | bytearray | memoryview,
        rgb888_off: bytes | bytearray | memoryview,
        *,
        start_frame: int = 0,
    ) -> tuple[RenderedFrame, RenderedFrame]:
        return (
            self.prepare(start_frame, rgb888_on, photodiode_state="on"),
            self.prepare(start_frame + 1, rgb888_off, photodiode_state="off"),
        )

    def packed_pair(
        self,
        rgb888_on: bytes | bytearray | memoryview,
        rgb888_off: bytes | bytearray | memoryview,
    ) -> bytes:
        first, second = self.prepare_pair(rgb888_on, rgb888_off)
        return bytes(first.data) + bytes(second.data)
