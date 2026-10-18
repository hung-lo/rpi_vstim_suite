from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rpi_vstim.core.config import Config
from rpi_vstim.protocols.visual_mapping.cache import FrameCache, FrameSetSpec, build_frame_cache
from rpi_vstim.protocols.visual_mapping.rendering import (
    display_render_settings,
    make_renderer,
    pack_rgb_frame,
    save_labeled_contact_sheet,
)

from . import DriftingGratingSettings, drift_direction_deg
from .stimulus import generate_grating_frame


def render_settings(config: Config, settings: DriftingGratingSettings) -> dict[str, Any]:
    return {
        "renderer_schema": 1,
        "display": display_render_settings(config),
        "protocol": {
            "orientations_deg": list(settings.orientations_deg),
            "stim_duration_s": settings.stim_duration_s,
            "stimulus_frame_count": settings.stimulus_frame_count,
            "temporal_frequency_hz": settings.temporal_frequency_hz,
            "spatial_frequency_cycles_per_cm": settings.spatial_frequency_cycles_per_cm,
            "contrast": settings.contrast,
            "mean_luminance": settings.mean_luminance,
            "starting_phase_deg": settings.starting_phase_deg,
            "grating_mode": settings.grating_mode,
            "rectangular_patch_geometry": (
                vars(settings.rectangular_patch_geometry)
                if settings.rectangular_patch_geometry is not None else None
            ),
        },
    }


def build_cache(config: Config, settings: DriftingGratingSettings, cache_root: Path) -> FrameCache:
    renderer = make_renderer(config)
    frame_size = renderer.stride_bytes * renderer.height_px
    gray = np.full((renderer.height_px, renderer.width_px, 3), 127, dtype=np.uint8)
    frame_sets = [FrameSetSpec("gray", 1, lambda _index: pack_rgb_frame(
        renderer, gray, photodiode_state="off", asset_key="gray:127"
    ))]
    for orientation_id, orientation in enumerate(settings.orientations_deg, start=1):
        name = f"orientation_{orientation_id:02d}"
        frame_sets.append(FrameSetSpec(
            name,
            settings.stimulus_frame_count,
            lambda index, angle=orientation, set_name=name: pack_rgb_frame(
                renderer,
                generate_grating_frame(
                    config, settings, bar_orientation_deg=angle, frame_index=index
                ),
                photodiode_state="on",
                asset_key=f"{set_name}:{index}",
            ),
        ))

    def write_artifacts(staging: Path):
        tiles = []
        for orientation_id, orientation in enumerate(settings.orientations_deg, start=1):
            direction = drift_direction_deg(orientation)
            tiles.append((
                f"{orientation_id}: bar {orientation:g} deg; drift {direction:g} deg",
                generate_grating_frame(
                    config, settings, bar_orientation_deg=orientation, frame_index=0
                ),
            ))
        return [save_labeled_contact_sheet(
            tiles, staging / "orientation_contact_sheet.png", columns=4, tile_width=256
        )]

    return build_frame_cache(
        cache_root,
        protocol="drifting-gratings",
        render_settings=render_settings(config, settings),
        frame_size_bytes=frame_size,
        frame_sets=frame_sets,
        write_artifacts=write_artifacts,
    )


def write_preview(config: Config, settings: DriftingGratingSettings, output_path: Path) -> Path:
    tiles = [
        (
            f"{index}: bar {angle:g} deg; drift {drift_direction_deg(angle):g} deg",
            generate_grating_frame(config, settings, bar_orientation_deg=angle, frame_index=0),
        )
        for index, angle in enumerate(settings.orientations_deg, start=1)
    ]
    return save_labeled_contact_sheet(tiles, output_path, columns=4, tile_width=256)
