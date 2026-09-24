from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhotodiodePatch:
    corner: str
    size_px: int
    on_value: int
    off_value: int

