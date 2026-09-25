from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import random
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
    image_count: int | None = None
    repeat_count: int = 1
    selection_seed: int = 777
    refresh_hz: float = 60.0
    image_duration_s: float = 0.5
    iti_frames: tuple[int, ...] = (42, 60)
    initial_gray_frames: int = 180
    final_gray_frames: int = 180
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
    if count is None:
        return values
    if count > len(values):
        raise ValueError("image selection count exceeds available images")
    return tuple(sorted(random.Random(seed).sample(values, count)))


def _shuffle_repetitions(images: Iterable[str], repeats: int, *, seed: int) -> tuple[str, ...]:
    values = tuple(images)
    if repeats < 1:
        raise ValueError("repeat_count must be at least 1")
    counts = Counter(value for value in values for _ in range(repeats))
    if not counts:
        return ()
    rng = random.Random(seed)
    result: list[str] = []
    previous = None
    while counts:
        candidates = []
        for value in counts:
            if value == previous:
                continue
            remaining = counts.copy()
            remaining[value] -= 1
            if not remaining[value]:
                del remaining[value]
            total = sum(remaining.values())
            feasible = not remaining or max(remaining.values()) <= (total + 1) // 2
            if value in remaining:
                feasible = feasible and remaining[value] <= total - remaining[value]
            if feasible:
                candidates.extend([value] * counts[value])
        if not candidates:
            raise ValueError("cannot avoid adjacent repeated images")
        value = rng.choice(candidates)
        counts[value] -= 1
        if counts[value] == 0:
            del counts[value]
        result.append(value)
        previous = value
    return tuple(result)


def build_plan(settings: NaturalImageSettings) -> SessionPlan:
    if settings.compatibility_profile not in FINAL_ITI_BY_PROFILE:
        raise ValueError(
            f"unsupported natural-image compatibility profile: {settings.compatibility_profile}"
        )
    if settings.trial_count is not None:
        selected = no_adjacent_repeat(settings.images, settings.trial_count, seed=settings.seed)
    else:
        selected_images = select_images(
            settings.images,
            count=settings.image_count,
            seed=settings.selection_seed,
        )
        selected = _shuffle_repetitions(
            selected_images,
            settings.repeat_count,
            seed=settings.seed,
        )
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
