from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rpi_vstim.core.config import Config
from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.renderer import ProductionFrameRenderer


def photodiode_patch(config: Config) -> PhotodiodePatch:
    settings = config.photodiode
    on_value = settings.on_value if settings.enabled else settings.off_value
    return PhotodiodePatch(settings.corner, settings.size_px, on_value, settings.off_value)


def make_renderer(config: Config) -> ProductionFrameRenderer:
    return ProductionFrameRenderer(
        config.display.width_px,
        config.display.height_px,
        config.display.pixel_format,
        photodiode=photodiode_patch(config),
    )


def pack_rgb_frame(
    renderer: ProductionFrameRenderer,
    rgb: np.ndarray,
    *,
    photodiode_state: str,
    asset_key: str,
) -> bytes:
    if rgb.dtype != np.uint8 or rgb.shape != (renderer.height_px, renderer.width_px, 3):
        raise ValueError("rendered RGB frame does not match display dimensions")
    return bytes(renderer.prepare_payload(
        rgb,
        photodiode_state=photodiode_state,
        asset_key=asset_key,
    ))


def save_labeled_contact_sheet(
    tiles: list[tuple[str, np.ndarray]],
    output_path: Path,
    *,
    columns: int,
    tile_width: int = 320,
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required for visual-mapping previews; install the images extra") from exc
    if not tiles or columns < 1:
        raise ValueError("contact sheet needs at least one tile and a positive column count")
    tile_height = max(1, round(tile_width * tiles[0][1].shape[0] / tiles[0][1].shape[1]))
    label_height = 28
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    for index, (label, frame) in enumerate(tiles):
        image = Image.fromarray(frame, mode="RGB")
        image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        sheet.paste(image, (x, y))
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + label_height), fill=(0, 0, 0))
        draw.text((x + 6, y + tile_height + 6), label, fill=(255, 255, 255))
        image.close()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    sheet.close()
    return output_path


def display_render_settings(config: Config) -> dict[str, Any]:
    return {
        "width_px": config.display.width_px,
        "height_px": config.display.height_px,
        "refresh_hz": config.display.refresh_hz,
        "pixel_format": config.display.pixel_format,
        "physical_width_cm": config.display.physical_width_cm,
        "physical_height_cm": config.display.physical_height_cm,
        "eye_distance_cm": config.display.eye_distance_cm,
        "background_gray_u8": 127,
        "photodiode": {
            "enabled": config.photodiode.enabled,
            "corner": config.photodiode.corner,
            "size_px": config.photodiode.size_px,
            "on_value": config.photodiode.on_value,
            "off_value": config.photodiode.off_value,
        },
    }
