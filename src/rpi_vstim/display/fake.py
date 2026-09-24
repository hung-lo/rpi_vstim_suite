from __future__ import annotations

from rpi_vstim.core.config import DisplayConfig
from rpi_vstim.core.timestamps import monotonic_ns, utc_ns

from .frame_program import FrameProgram
from .models import DisplayInfo, DisplayResult


class FakeDisplayBackend:
    """Deterministic in-memory display for tests; it never sleeps or opens a device."""

    name = "fake"

    def __init__(self) -> None:
        self.config: DisplayConfig | None = None
        self.presented: list[tuple[str, int]] = []

    def open(self, config: DisplayConfig) -> DisplayInfo:
        self.config = config
        return DisplayInfo(self.name, config.connector, f"{config.width_px}x{config.height_px}@{config.refresh_hz}", config.pixel_format)

    def validate_program(self, program: FrameProgram) -> None:
        program.validate()
        if self.config is None:
            raise RuntimeError("display is not open")
        if (program.width_px, program.height_px, program.pixel_format) != (
            self.config.width_px,
            self.config.height_px,
            self.config.pixel_format,
        ):
            raise ValueError("frame program does not match display configuration")

    def present(self, program: FrameProgram, *, sequence_id: str) -> DisplayResult:
        self.validate_program(program)
        self.presented.append((sequence_id, program.frame_count))
        first_mono = monotonic_ns()
        return DisplayResult(
            self.name,
            self.config.connector,
            f"{self.config.width_px}x{self.config.height_px}@{self.config.refresh_hz}",
            self.config.pixel_format,
            sequence_id,
            program.frame_count,
            program.frame_count,
            first_mono,
            first_mono,
            utc_ns(),
        )

    def present_color(self, rgb: tuple[int, int, int], *, frames: int) -> DisplayResult:
        if len(rgb) != 3 or any(not 0 <= value <= 255 for value in rgb):
            raise ValueError("rgb must contain three values from 0 to 255")
        if self.config is None:
            raise RuntimeError("display is not open")
        program = FrameProgram(self.config.width_px, self.config.height_px, self.config.refresh_hz, self.config.pixel_format, frames)
        return self.present(program, sequence_id=f"color:{rgb}")

    def close(self) -> None:
        self.config = None
