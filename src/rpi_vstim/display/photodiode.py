from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhotodiodePatch:
    corner: str
    size_px: int
    on_value: int
    off_value: int

    def __post_init__(self) -> None:
        if self.corner not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            raise ValueError(f"unsupported photodiode corner: {self.corner}")
        if self.size_px <= 0 or not 0 <= self.on_value <= 255 or not 0 <= self.off_value <= 255:
            raise ValueError("invalid photodiode patch")


def patch_bounds(width_px: int, height_px: int, patch: PhotodiodePatch) -> tuple[int, int, int, int]:
    if min(width_px, height_px) <= 0:
        raise ValueError("display dimensions must be positive")
    size = min(patch.size_px, width_px, height_px)
    x = 0 if "left" in patch.corner else width_px - size
    y = 0 if "top" in patch.corner else height_px - size
    return x, y, size, size


def patch_value(patch: PhotodiodePatch, state: str | bool) -> int:
    if isinstance(state, str):
        if state not in {"on", "off"}:
            raise ValueError("photodiode state must be 'on' or 'off'")
        state = state == "on"
    return patch.on_value if state else patch.off_value
