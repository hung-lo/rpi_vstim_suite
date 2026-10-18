from __future__ import annotations

from functools import lru_cache

import numpy as np

from rpi_vstim.core.config import Config

from . import DriftingGratingSettings, normalize_orientation_deg


@lru_cache(maxsize=4)
def _coordinate_grids(width: int, height: int, width_cm: float, height_cm: float):
    x_cm = (np.arange(width, dtype=np.float64) - (width - 1) / 2.0) * (width_cm / width)
    y_cm = ((height - 1) / 2.0 - np.arange(height, dtype=np.float64)) * (height_cm / height)
    return np.meshgrid(x_cm, y_cm)


def generate_grating_frame(
    config: Config,
    settings: DriftingGratingSettings,
    *,
    bar_orientation_deg: float,
    frame_index: int,
) -> np.ndarray:
    """Render the frozen sine-grating definition at one nominal refresh."""
    if frame_index < 0:
        raise ValueError("frame_index must be non-negative")
    display = config.display
    x_grid, y_grid = _coordinate_grids(
        display.width_px,
        display.height_px,
        display.physical_width_cm,
        display.physical_height_cm,
    )
    theta = np.deg2rad(normalize_orientation_deg(bar_orientation_deg))
    carrier_cm = -np.sin(theta) * x_grid + np.cos(theta) * y_grid
    phase = np.deg2rad(settings.starting_phase_deg) + (
        2.0 * np.pi * settings.temporal_frequency_hz * frame_index / display.refresh_hz
    )
    sinusoid = np.sin(2.0 * np.pi * settings.spatial_frequency_cycles_per_cm * carrier_cm + phase)
    luminance = settings.mean_luminance * (1.0 + settings.contrast * sinusoid)
    if np.any(luminance < -1e-12) or np.any(luminance > 1.0 + 1e-12):
        raise ValueError("grating luminance exceeds the normalized display range")
    if settings.grating_mode == "rectangular_patch":
        geometry = settings.rectangular_patch_geometry
        assert geometry is not None
        if (
            abs(geometry.center_x_cm) + geometry.width_cm / 2 > display.physical_width_cm / 2
            or abs(geometry.center_y_cm) + geometry.height_cm / 2 > display.physical_height_cm / 2
        ):
            raise ValueError("rectangular patch geometry exceeds the configured active screen")
        mask = (
            (np.abs(x_grid - geometry.center_x_cm) <= geometry.width_cm / 2)
            & (np.abs(y_grid - geometry.center_y_cm) <= geometry.height_cm / 2)
        )
        luminance = np.where(mask, luminance, 127 / 255)
    frame = np.rint(np.clip(luminance, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.repeat(frame[:, :, None], 3, axis=2)
