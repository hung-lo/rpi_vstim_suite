"""Fail-closed KMS boundary backed by the read-only Phase 3 probe."""

from __future__ import annotations

import math
import tempfile
from collections.abc import Iterable
from pathlib import Path

from rpi_vstim.core.config import DisplayConfig

from .diagnostics import probe_config
from .frame_program import FrameProgram
from .models import DisplayInfo, DisplayResult
from .native_probe import display_result_from_probe, run_native_probe, run_native_sequence
from .photodiode import PhotodiodePatch
from .renderer import ProductionFrameRenderer
from .transport import DisplaySequenceFrame


class KmsDisplayBackend:
    name = "kms"

    def __init__(
        self,
        *,
        native_binary: Path | str | None = None,
        photodiode: PhotodiodePatch | None = None,
        use_lease: bool | None = None,
    ) -> None:
        self.config: DisplayConfig | None = None
        self.info: DisplayInfo | None = None
        self.native_binary = native_binary
        self.photodiode = photodiode or PhotodiodePatch("bottom_right", 50, 255, 0)
        self._use_lease_override = use_lease
        self.use_lease = False
        self.renderer: ProductionFrameRenderer | None = None
        self.last_probe_payload: dict[str, object] | None = None

    def open(self, config: DisplayConfig) -> DisplayInfo:
        if config.ownership not in {"direct", "lease"}:
            raise ValueError(f"unsupported display ownership: {config.ownership}")
        result = probe_config(config)
        selected = result["stimulus"]
        self.config = config
        self.use_lease = (
            config.ownership == "lease"
            if self._use_lease_override is None
            else self._use_lease_override
        )
        self.info = DisplayInfo(
            self.name,
            str(selected["connector"]),
            f"{selected['mode']}@{float(selected['refresh_hz']):g}",
            config.pixel_format,
        )
        self.renderer = ProductionFrameRenderer(
            config.width_px,
            config.height_px,
            config.pixel_format,
            photodiode=self.photodiode,
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
        return self._present(program.frame_count, sequence_id=sequence_id)

    def present_color(self, rgb: tuple[int, int, int], *, frames: int) -> DisplayResult:
        if len(rgb) != 3 or any(not 0 <= value <= 255 for value in rgb):
            raise ValueError("rgb must contain three values from 0 to 255")
        if self.config is None:
            raise RuntimeError("display is not open")
        return self._present(frames, sequence_id=f"color:{rgb}", color=rgb)

    def present_rgb_pair(
        self,
        rgb888_on: bytes | bytearray | memoryview,
        rgb888_off: bytes | bytearray | memoryview,
        *,
        frames: int,
        sequence_id: str,
    ) -> DisplayResult:
        if self.config is None or self.renderer is None:
            raise RuntimeError("display is not open")
        frame_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix="rpi-vstim-frame-pair-", suffix=".raw", delete=False
            ) as frame_file:
                frame_path = Path(frame_file.name)
                frame_file.write(self.renderer.packed_pair(rgb888_on, rgb888_off))
            return self._present(
                frames,
                sequence_id=sequence_id,
                frame_file=frame_path,
            )
        finally:
            if frame_path is not None:
                frame_path.unlink(missing_ok=True)

    def present_sequence(self, frames: Iterable[DisplaySequenceFrame]) -> dict[str, object]:
        if self.config is None:
            raise RuntimeError("display is not open")
        try:
            payload = run_native_sequence(
                self.config,
                frames,
                binary=self.native_binary,
                patch_size=self.photodiode.size_px,
                patch_corner=self.photodiode.corner,
                patch_on=self.photodiode.on_value,
                patch_off=self.photodiode.off_value,
                lease=self.use_lease,
            )
            self.last_probe_payload = payload
            return payload
        except Exception:
            self.close()
            raise

    def _present(
        self,
        frames: int,
        *,
        sequence_id: str,
        color: tuple[int, int, int] | None = None,
        frame_file: Path | None = None,
    ) -> DisplayResult:
        if self.config is None:
            raise RuntimeError("display is not open")
        try:
            payload = run_native_probe(
                self.config,
                frames=frames,
                binary=self.native_binary,
                color=color,
                patch_size=self.photodiode.size_px,
                patch_corner=self.photodiode.corner,
                patch_on=self.photodiode.on_value,
                patch_off=self.photodiode.off_value,
                lease=self.use_lease,
                frame_file=frame_file,
            )
            self.last_probe_payload = payload
        except Exception:
            self.close()
            raise
        return display_result_from_probe(payload, self.config, sequence_id=sequence_id)

    def close(self) -> None:
        self.config = None
        self.info = None
        self.renderer = None
        self.last_probe_payload = None
