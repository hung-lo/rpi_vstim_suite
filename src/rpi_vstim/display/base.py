from __future__ import annotations

from typing import Protocol

from rpi_vstim.core.config import DisplayConfig

from .frame_program import FrameProgram
from .models import DisplayInfo, DisplayResult


class DisplayBackend(Protocol):
    def open(self, config: DisplayConfig) -> DisplayInfo: ...
    def validate_program(self, program: FrameProgram) -> None: ...
    def present(self, program: FrameProgram, *, sequence_id: str) -> DisplayResult: ...
    def present_color(self, rgb: tuple[int, int, int], *, frames: int) -> DisplayResult: ...
    def close(self) -> None: ...

