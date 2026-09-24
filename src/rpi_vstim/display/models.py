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
    first_page_flip_monotonic_ns: int | None = None
    last_page_flip_monotonic_ns: int | None = None
    first_page_flip_realtime_ns: int | None = None
    mean_vblank_interval_us: float | None = None
    std_vblank_interval_us: float | None = None
    maximum_vblank_interval_us: float | None = None
    missed_vblank_count: int = 0
    aborted: bool = False
    error: str | None = None

