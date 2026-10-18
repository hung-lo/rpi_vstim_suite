from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rpi_vstim.core.config import Config
from rpi_vstim.protocols.visual_mapping.cache import FrameSetSpec, build_frame_cache
from rpi_vstim.protocols.visual_mapping.rendering import (
    display_render_settings,
    make_renderer,
    pack_rgb_frame,
    save_labeled_contact_sheet,
)

from . import DIRECTIONS, RetinotopySettings
from .stimulus import generate_retinotopy_frame


def render_settings(config: Config, settings: RetinotopySettings) -> dict[str, Any]:
    return {
        "renderer_schema": 1,
        "display": display_render_settings(config),
        "protocol": {
            "sweep_duration_s": settings.sweep_duration_s,
            "movement_frame_rate_hz": settings.movement_frame_rate_hz,
            "source_frame_count": round(settings.sweep_duration_s * settings.movement_frame_rate_hz),
            "bar_width_fraction": settings.bar_width_fraction,
            "enabled_directions": list(settings.enabled_directions),
            "background_gray_u8": 127,
            "black_u8": 0,
            "white_u8": 255,
            "bar_polarity": "black on negative-coordinate side, white on positive-coordinate side",
        },
    }


def build_cache(config: Config, settings: RetinotopySettings, cache_root: Path):
    renderer = make_renderer(config)
    frame_size = renderer.stride_bytes * renderer.height_px
    gray = np.full((renderer.height_px, renderer.width_px, 3), 127, dtype=np.uint8)
    frame_sets = [FrameSetSpec("gray", 1, lambda _index: pack_rgb_frame(
        renderer, gray, photodiode_state="off", asset_key="gray:127"
    ))]
    source_count = round(settings.sweep_duration_s * settings.movement_frame_rate_hz)
    axes = tuple(dict.fromkeys(DIRECTIONS[direction][4] for direction in settings.enabled_directions))
    for axis in axes:
        frame_sets.append(FrameSetSpec(
            axis,
            source_count,
            lambda index, selected_axis=axis: pack_rgb_frame(
                renderer,
                generate_retinotopy_frame(
                    config,
                    settings,
                    direction=("left_to_right" if selected_axis == "x" else "top_to_bottom"),
                    source_frame_index=index,
                ),
                photodiode_state="on",
                asset_key=f"retinotopy:{selected_axis}:{index}",
            ),
        ))

    def write_artifacts(staging: Path):
        tiles = []
        for direction in settings.enabled_directions:
            for label, index in (("start", 0), ("middle", source_count // 2), ("end", source_count - 1)):
                tiles.append((
                    f"{direction}: {label}",
                    generate_retinotopy_frame(
                        config, settings, direction=direction, source_frame_index=index
                    ),
                ))
        return [save_labeled_contact_sheet(
            tiles, staging / "direction_contact_sheet.png", columns=3, tile_width=320
        )]

    return build_frame_cache(
        cache_root,
        protocol="retinotopy",
        render_settings=render_settings(config, settings),
        frame_size_bytes=frame_size,
        frame_sets=frame_sets,
        write_artifacts=write_artifacts,
    )


def write_preview(config: Config, settings: RetinotopySettings, output_path: Path) -> Path:
    source_count = round(settings.sweep_duration_s * settings.movement_frame_rate_hz)
    tiles = []
    for direction in settings.enabled_directions:
        for label, index in (("start", 0), ("middle", source_count // 2), ("end", source_count - 1)):
            tiles.append((
                f"{direction}: {label}",
                generate_retinotopy_frame(config, settings, direction=direction, source_frame_index=index),
            ))
    return save_labeled_contact_sheet(tiles, output_path, columns=3, tile_width=320)
