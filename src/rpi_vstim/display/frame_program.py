from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameProgram:
    width_px: int
    height_px: int
    refresh_hz: float
    pixel_format: str
    frame_count: int
    unique_frame_count: int = 1

    def validate(self) -> None:
        if min(self.width_px, self.height_px, self.refresh_hz, self.frame_count, self.unique_frame_count) <= 0:
            raise ValueError("frame program dimensions and counts must be positive")
        if self.unique_frame_count > self.frame_count:
            raise ValueError("unique_frame_count cannot exceed frame_count")

