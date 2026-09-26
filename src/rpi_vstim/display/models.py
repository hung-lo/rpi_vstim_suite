from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DisplayInfo:
    backend_name: str
    connector: str
    mode: str
    pixel_format: str


@dataclass(frozen=True)
class DisplayResult:
    backend_name: str
    connector: str
    mode: str
    pixel_format: str
    sequence_id: str
    requested_frame_count: int
    completed_frame_count: int
    first_page_flip_kernel_event_ns: int | None = None
    last_page_flip_kernel_event_ns: int | None = None
    first_page_flip_callback_monotonic_ns: int | None = None
    last_page_flip_callback_monotonic_ns: int | None = None
    first_page_flip_callback_realtime_ns: int | None = None
    last_page_flip_callback_realtime_ns: int | None = None
    timing_source: str | None = None
    kernel_timestamp_clock: str | None = None
    mean_vblank_interval_us: float | None = None
    std_vblank_interval_us: float | None = None
    maximum_vblank_interval_us: float | None = None
    missed_vblank_count: int = 0
    aborted: bool = False
    error: str | None = None
    p95_vblank_interval_us: float | None = None
    p99_vblank_interval_us: float | None = None
    intervals_outside_tolerance: int = 0
    estimated_dropped_frame_count: int = 0
    photodiode_state: str | None = None
