from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rpi_vstim.core.duration import seconds_to_frames
from rpi_vstim.core.plan import (
    PlannedEvent,
    SessionPlan,
    no_adjacent_repeat,
    seeded_choices,
    with_frame_offsets,
)

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"})
FINAL_ITI_BY_PROFILE = {
    "natural_legacy_plain": True,
    "natural_legacy_camera": False,
}


@dataclass(frozen=True)
class NaturalImageSettings:
    images: tuple[str, ...]
    seed: int = 0
    trial_count: int | None = None
    refresh_hz: float = 60.0
    image_duration_s: float = 0.5
    iti_frames: tuple[int, ...] = (30, 60)
    initial_gray_frames: int = 60
    final_gray_frames: int = 60
    compatibility_profile: str = "natural_legacy_plain"
    camera_ids: tuple[str, ...] = ()


def discover_images(root: Path) -> tuple[str, ...]:
    """Return sorted relative image paths without opening or decoding assets."""
    if not root.is_dir():
        raise FileNotFoundError(root)
    return tuple(
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def select_images(images: Iterable[str], *, count: int | None, seed: int) -> tuple[str, ...]:
    values = tuple(images)
    return no_adjacent_repeat(values, len(values) if count is None else count, seed=seed)


def build_plan(settings: NaturalImageSettings) -> SessionPlan:
    if settings.compatibility_profile not in FINAL_ITI_BY_PROFILE:
        raise ValueError(
            f"unsupported natural-image compatibility profile: {settings.compatibility_profile}"
        )
    selected = select_images(settings.images, count=settings.trial_count, seed=settings.seed)
    image_frames = seconds_to_frames(settings.image_duration_s, settings.refresh_hz)
    itis = seeded_choices(settings.iti_frames, len(selected), seed=settings.seed + 1)
    events: list[PlannedEvent] = [
        PlannedEvent(
            "initial-gray",
            "gray",
            settings.initial_gray_frames,
            phase="PRE",
            photodiode="off",
        )
    ]
    for index, image in enumerate(selected):
        events.append(
            PlannedEvent(
                f"image-{index + 1}",
                "image",
                image_frames,
                trial_id=str(index + 1),
                sequence_id=f"image-{index + 1}",
                photodiode="on",
                metadata={"image": image},
            )
        )
        if index < len(selected) - 1 or FINAL_ITI_BY_PROFILE[settings.compatibility_profile]:
            events.append(
                PlannedEvent(
                    f"iti-{index + 1}",
                    "iti",
                    itis[index],
                    trial_id=str(index + 1),
                    photodiode="off",
                )
            )
    events.append(
        PlannedEvent("final-gray", "gray", settings.final_gray_frames, phase="POST", photodiode="off")
    )
    return SessionPlan(
        "natural-images",
        settings.seed,
        with_frame_offsets(events),
        metadata={
            "selected_images": list(selected),
            "compatibility_profile": settings.compatibility_profile,
            "camera_ids": list(settings.camera_ids),
        },
    )


class NaturalImagesProtocol:
    name = "natural-images"
    version = "software-groundwork"

    def build_plan(self, settings: NaturalImageSettings) -> SessionPlan:
        return build_plan(settings)


protocol = NaturalImagesProtocol()
