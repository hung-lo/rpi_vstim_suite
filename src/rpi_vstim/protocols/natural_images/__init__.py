from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rpi_vstim.core.assets import IMAGE_SUFFIXES
from rpi_vstim.core.duration import milliseconds_to_frames, seconds_to_frames
from rpi_vstim.core.plan import (
    PlannedEvent,
    SessionPlan,
    no_adjacent_repeat,
    seeded_choices,
    with_frame_offsets,
)

FINAL_ITI_BY_PROFILE = {
    "natural_legacy_plain": True,
    "natural_legacy_camera": False,
    "portable_display_only": True,
}
ASSET_TRANSFORM_BY_PROFILE = {
    "natural_legacy_plain": "crop",
    "natural_legacy_camera": "crop",
    "portable_display_only": "crop",
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
    image_duration_ms: float | None = None
    iti_frames: tuple[int, ...] = (42, 60)
    iti_duration_ms: tuple[float, ...] | None = None
    initial_gray_frames: int = 180
    initial_gray_duration_ms: float | None = None
    final_gray_frames: int = 180
    final_gray_duration_ms: float | None = None
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
    buckets = {value: [value] * repeats for value in values}
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    counts = {value: len(bucket) for value, bucket in buckets.items()}
    if not counts:
        return ()
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
                candidates.append(value)
        if not candidates:
            raise ValueError("cannot avoid adjacent repeated images")
        selected_index = rng.randrange(sum(counts[value] for value in candidates))
        value = candidates[-1]
        for candidate in candidates:
            selected_index -= counts[candidate]
            if selected_index < 0:
                value = candidate
                break
        counts[value] -= 1
        if counts[value] == 0:
            del counts[value]
        buckets[value].pop()
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
    adaptive = settings.compatibility_profile == "portable_display_only"
    if adaptive:
        if settings.initial_gray_duration_ms is None or settings.final_gray_duration_ms is None:
            raise ValueError("portable_display_only requires gray durations in milliseconds")
        if not settings.iti_duration_ms:
            raise ValueError("portable_display_only requires ITI durations in milliseconds")
        requested_image_ms = (
            settings.image_duration_ms
            if settings.image_duration_ms is not None
            else settings.image_duration_s * 1000
        )
        image_frames = milliseconds_to_frames(requested_image_ms, settings.refresh_hz)
        initial_gray_frames = milliseconds_to_frames(
            settings.initial_gray_duration_ms, settings.refresh_hz
        )
        final_gray_frames = milliseconds_to_frames(
            settings.final_gray_duration_ms, settings.refresh_hz
        )
        requested_itis = _seeded_iti_values(
            settings.iti_duration_ms, len(selected), seed=settings.seed + 1
        )
        itis = tuple(milliseconds_to_frames(value, settings.refresh_hz) for value in requested_itis)
        duration_provenance = {
            "rounding_policy": "nearest frame; exact halves round up; nonzero requests use at least one frame",
            "image": _duration_record(requested_image_ms, image_frames, settings.refresh_hz),
            "initial_gray": _duration_record(
                settings.initial_gray_duration_ms, initial_gray_frames, settings.refresh_hz
            ),
            "final_gray": _duration_record(
                settings.final_gray_duration_ms, final_gray_frames, settings.refresh_hz
            ),
            "iti": {},
        }
    else:
        image_frames = seconds_to_frames(settings.image_duration_s, settings.refresh_hz)
        initial_gray_frames = settings.initial_gray_frames
        final_gray_frames = settings.final_gray_frames
        requested_itis = _seeded_iti_frames(settings.iti_frames, len(selected), seed=settings.seed + 1)
        itis = requested_itis
        duration_provenance = {
            "rounding_policy": "strict integer frame counts",
            "image": _duration_record(
                settings.image_duration_s * 1000, image_frames, settings.refresh_hz
            ),
            "initial_gray": _frame_duration_record(initial_gray_frames, settings.refresh_hz),
            "final_gray": _frame_duration_record(final_gray_frames, settings.refresh_hz),
            "iti": {},
        }
    events: list[PlannedEvent] = [
        PlannedEvent(
            "initial-gray",
            "gray",
            initial_gray_frames,
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
            if adaptive:
                duration_provenance["iti"][f"iti-{index + 1}"] = _duration_record(
                    requested_itis[index], itis[index], settings.refresh_hz
                )
            else:
                duration_provenance["iti"][f"iti-{index + 1}"] = _frame_duration_record(
                    itis[index], settings.refresh_hz
                )
    events.append(
        PlannedEvent("final-gray", "gray", final_gray_frames, phase="POST", photodiode="off")
    )
    duration_provenance["final_planned_total_frame_count"] = sum(
        event.frame_count for event in events
    )
    duration_provenance["nominal_total_duration_ms"] = (
        duration_provenance["final_planned_total_frame_count"] * 1000 / settings.refresh_hz
    )
    metadata = {
        "selected_images": list(selected),
        "compatibility_profile": settings.compatibility_profile,
        "asset_transform": ASSET_TRANSFORM_BY_PROFILE[settings.compatibility_profile],
        "background_gray": 127,
        "photodiode_patch_policy": "legacy_top_right_120px",
        "camera_ids": list(settings.camera_ids),
    }
    if adaptive:
        metadata.update(
            duration_timing_mode="refresh_adaptive",
            duration_provenance=duration_provenance,
        )
    plan = SessionPlan(
        "natural-images",
        settings.seed,
        with_frame_offsets(events),
        metadata=metadata,
    )
    return plan


def _duration_record(requested_ms: float, frames: int, refresh_hz: float) -> dict[str, float | int]:
    nominal_ms = frames * 1000 / refresh_hz
    return {
        "requested_ms": requested_ms,
        "resolved_frames": frames,
        "nominal_duration_ms": nominal_ms,
        "quantization_error_ms": nominal_ms - requested_ms,
    }


def _frame_duration_record(frames: int, refresh_hz: float) -> dict[str, float | int]:
    nominal_ms = frames * 1000 / refresh_hz
    return _duration_record(nominal_ms, frames, refresh_hz)


def _seeded_iti_values(values: tuple[float, ...], count: int, *, seed: int) -> tuple[float, ...]:
    if len(values) == 2:
        low, high = values
        if low > high:
            raise ValueError("iti_duration_ms bounds must be ordered")
        rng = random.Random(seed)
        if all(type(value) is int for value in values):
            return tuple(rng.randint(low, high) for _ in range(count))
        return tuple(rng.uniform(low, high) for _ in range(count))
    if not values:
        raise ValueError("iti_duration_ms must not be empty")
    return tuple(random.Random(seed).choices(values, k=count))


def _seeded_iti_frames(values: tuple[int, ...], count: int, *, seed: int) -> tuple[int, ...]:
    if len(values) == 2:
        low, high = values
        if low > high:
            raise ValueError("iti_frames bounds must be ordered")
        rng = random.Random(seed)
        return tuple(rng.randint(low, high) for _ in range(count))
    return seeded_choices(values, count, seed=seed)


class NaturalImagesProtocol:
    name = "natural-images"
    version = "software-groundwork"

    def build_plan(self, settings: NaturalImageSettings) -> SessionPlan:
        return build_plan(settings)


protocol = NaturalImagesProtocol()
