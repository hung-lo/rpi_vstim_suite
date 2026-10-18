from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from rpi_vstim.core.config import Config
from rpi_vstim.core.plan import SessionPlan
from rpi_vstim.protocols.visual_mapping.geometry import (
    pixel_to_screen_cm,
    screen_cm_to_visual_angle_deg,
)

from . import DIRECTIONS, RetinotopySettings, refreshes_per_source_frame
from .stimulus import bar_width_px, boundary_positions_px

FRAME_PLAN_FIELDS = (
    "sweep_index",
    "repeat_number",
    "direction",
    "axis",
    "screen_width_px",
    "screen_height_px",
    "active_width_cm",
    "active_height_cm",
    "eye_screen_distance_cm",
    "screen_center_convention",
    "render_cache_key",
    "cache_sha256",
    "cache_frame_set",
    "cache_frame_index",
    "source_frame_index",
    "planned_relative_time_s",
    "first_nominal_display_refresh_index",
    "refresh_count",
    "normalized_sweep_position",
    "normalized_boundary_position",
    "nominal_boundary_position_px",
    "boundary_position_px",
    "bar_width_px",
    "black_start_px",
    "black_end_px",
    "white_start_px",
    "white_end_px",
    "boundary_screen_x_cm",
    "boundary_screen_y_cm",
    "boundary_visual_angle_x_deg",
    "boundary_visual_angle_y_deg",
    "first_kms_kernel_event_ns",
    "first_kms_callback_monotonic_ns",
)


def build_frame_plan_rows(
    config: Config,
    settings: RetinotopySettings,
    plan: SessionPlan,
    cache: Any | None = None,
) -> list[dict[str, Any]]:
    source_count = round(settings.sweep_duration_s * settings.movement_frame_rate_hz)
    refresh_counts = refreshes_per_source_frame(
        source_count, settings.refresh_hz, settings.movement_frame_rate_hz
    )
    rows: list[dict[str, Any]] = []
    for event in plan.events:
        if event.kind != "retinotopy-sweep":
            continue
        direction = str(event.metadata["direction"])
        definition = DIRECTIONS[direction]
        axis = definition.axis
        cache_axis = definition.movement_axis
        width = bar_width_px(config, settings, direction)
        dimension = config.display.width_px if definition.movement_axis == "x" else config.display.height_px
        positions = boundary_positions_px(config, settings, direction)
        global_refresh = event.planned_start_frame
        for source_index, (boundary, refresh_count) in enumerate(zip(positions, refresh_counts)):
            nominal_boundary = float(boundary)
            rendered_boundary = round(nominal_boundary)
            cache_index = (
                source_index
                if direction in {"left_to_right", "top_to_bottom"}
                else source_count - 1 - source_index
            )
            if definition.movement_axis == "x":
                black_start, black_end = rendered_boundary - width, rendered_boundary
                white_start, white_end = rendered_boundary, rendered_boundary + width
                x_px, y_px = rendered_boundary, (config.display.height_px - 1) / 2.0
            else:
                black_start, black_end = rendered_boundary - width, rendered_boundary
                white_start, white_end = rendered_boundary, rendered_boundary + width
                x_px, y_px = (config.display.width_px - 1) / 2.0, rendered_boundary
            x_cm, y_cm = pixel_to_screen_cm(config, x_px, y_px)
            angle_x, angle_y = screen_cm_to_visual_angle_deg(config, x_cm, y_cm)
            rows.append({
                "sweep_index": int(event.trial_id or 0),
                "repeat_number": int(event.metadata["repeat_number"]),
                "direction": direction,
                "axis": axis,
                "screen_width_px": config.display.width_px,
                "screen_height_px": config.display.height_px,
                "active_width_cm": config.display.physical_width_cm,
                "active_height_cm": config.display.physical_height_cm,
                "eye_screen_distance_cm": config.display.eye_distance_cm,
                "screen_center_convention": "pixel-grid center; +x right; +y up",
                "render_cache_key": cache.cache_key if cache is not None else "",
                "cache_sha256": (
                    cache.manifest["frame_sets"][cache_axis]["sha256"]
                    if cache is not None else ""
                ),
                "cache_frame_set": cache_axis,
                "cache_frame_index": cache_index,
                "source_frame_index": source_index,
                "planned_relative_time_s": global_refresh / settings.refresh_hz,
                "first_nominal_display_refresh_index": global_refresh,
                "refresh_count": refresh_count,
                "normalized_sweep_position": source_index / max(source_count - 1, 1),
                "normalized_boundary_position": (nominal_boundary + width) / (dimension + 2 * width),
                "nominal_boundary_position_px": nominal_boundary,
                "boundary_position_px": rendered_boundary,
                "bar_width_px": width,
                "black_start_px": black_start,
                "black_end_px": black_end,
                "white_start_px": white_start,
                "white_end_px": white_end,
                "boundary_screen_x_cm": x_cm,
                "boundary_screen_y_cm": y_cm,
                "boundary_visual_angle_x_deg": angle_x,
                "boundary_visual_angle_y_deg": angle_y,
                "first_kms_kernel_event_ns": "",
                "first_kms_callback_monotonic_ns": "",
            })
            global_refresh += refresh_count
    return rows


def write_frame_plan(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FRAME_PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def update_actual_kms_mapping(
    rows: list[dict[str, Any]],
    flip_events: list[dict[str, Any]],
) -> None:
    by_frame = {int(item["frame_index"]): item for item in flip_events if "frame_index" in item}
    for row in rows:
        item = by_frame.get(int(row["first_nominal_display_refresh_index"]))
        if item is None:
            continue
        row["first_kms_kernel_event_ns"] = item.get("kernel_event_ns", "")
        row["first_kms_callback_monotonic_ns"] = item.get("callback_monotonic_ns", "")


