"""Fail-closed KMS boundary backed by the read-only Phase 3 probe."""

from __future__ import annotations

import math

from rpi_vstim.core.config import DisplayConfig

from .diagnostics import probe_config
from .frame_program import FrameProgram
from .models import DisplayInfo, DisplayResult


class KmsDisplayBackend:
    name = "kms"

    def __init__(self) -> None:
        self.config: DisplayConfig | None = None
        self.info: DisplayInfo | None = None

    def open(self, config):
        result = probe_config(config)
        selected = result["stimulus"]
        self.config = config
        self.info = DisplayInfo(
            self.name,
            str(selected["connector"]),
            f"{selected['mode']}@{float(selected['refresh_hz']):g}",
            config.pixel_format,
        )
        return self.info

    def validate_program(self, program: FrameProgram) -> None:
        if self.config is None:
            raise RuntimeError("display is not open")
        program.validate()
        if (program.width_px, program.height_px, program.pixel_format) != (
            self.config.width_px,
            self.config.height_px,
            self.config.pixel_format,
        ):
            raise ValueError("frame program does not match display configuration")
        if not math.isclose(program.refresh_hz, self.config.refresh_hz, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("frame program refresh_hz does not match display configuration")

    def present(self, program: FrameProgram, *, sequence_id: str) -> DisplayResult:
        self.validate_program(program)
        raise RuntimeError("native page-flip presentation is not enabled by the Phase 3 probe")

    def present_color(self, rgb: tuple[int, int, int], *, frames: int) -> DisplayResult:
        if len(rgb) != 3 or any(not 0 <= value <= 255 for value in rgb):
            raise ValueError("rgb must contain three values from 0 to 255")
        if self.config is None:
            raise RuntimeError("display is not open")
        return self.present(
            FrameProgram(
                self.config.width_px,
                self.config.height_px,
                self.config.refresh_hz,
                self.config.pixel_format,
                frames,
            ),
            sequence_id=f"color:{rgb}",
        )

    def close(self) -> None:
        self.config = None
        self.info = None
