#!/usr/bin/env python3
"""Validate the real natural-image corpus and optionally show a short subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tracemalloc
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from PIL import Image

from rpi_vstim.core.assets import AssetPreparer, AssetResolver
from rpi_vstim.core.config import Config, load_config
from rpi_vstim.display.kms import KmsDisplayBackend
from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.renderer import ProductionFrameRenderer
from rpi_vstim.display.transport import DisplaySequenceFrame, DisplaySequenceMetadata

EXPECTED_NAMES = tuple(f"natimg_center_{index:04d}.png" for index in range(2800))
EXPECTED_DIMENSIONS = (90, 68)
EXPECTED_MODE = "L"
DEFAULT_DISPLAY_SIZE = (1024, 600)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def inspect_archive(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        directories = [info.filename for info in infos if info.is_dir()]
        _check(len(directories) == 1, f"expected one archive directory, got {directories!r}")
        archive_root = directories[0].rstrip("/")
        names: list[str] = []
        dimensions: set[tuple[int, int]] = set()
        modes: set[str] = set()
        for info in infos:
            path_parts = PurePosixPath(info.filename).parts
            _check(
                not PurePosixPath(info.filename).is_absolute(),
                f"absolute member: {info.filename}",
            )
            _check(".." not in path_parts, f"path traversal member: {info.filename}")
            if info.is_dir():
                _check(
                    info.filename == f"{archive_root}/",
                    f"unexpected directory: {info.filename}",
                )
                continue
            _check(
                len(path_parts) == 2 and path_parts[0] == archive_root,
                f"unexpected member path: {info.filename}",
            )
            names.append(path_parts[1])
            with archive.open(info) as source, Image.open(source) as image:
                dimensions.add(image.size)
                modes.add(image.mode)
                image.verify()
        _check(len(infos) == 2801, f"expected 2801 archive members, got {len(infos)}")
        _check(
            tuple(sorted(names)) == EXPECTED_NAMES,
            "archive image names are not exactly 0000..2799",
        )
        _check(archive.testzip() is None, "archive CRC validation failed")
        _check(dimensions == {EXPECTED_DIMENSIONS}, f"archive dimensions: {dimensions}")
        _check(modes == {EXPECTED_MODE}, f"archive modes: {modes}")
        return {
            "members": len(infos),
            "images": len(names),
            "archive_root": archive_root,
            "dimensions": list(EXPECTED_DIMENSIONS),
            "mode": EXPECTED_MODE,
        }


def _legacy_crop(path: Path, target_size: tuple[int, int]) -> bytes:
    """Independent expression of the frozen centered aspect-preserving crop."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    source_width, source_height = image.size
    target_width, target_height = target_size
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    if source_ratio >= target_ratio:
        crop_width, crop_height = target_ratio * source_height, source_height
    else:
        crop_width, crop_height = source_width, source_width / target_ratio
    left = (source_width - crop_width) * 0.5
    top = (source_height - crop_height) * 0.5
    return image.resize(
        target_size,
        Image.Resampling.LANCZOS,
        box=(left, top, left + crop_width, top + crop_height),
    ).tobytes()


def validate_assets(root: Path, *, width: int, height: int, pixel_format: str) -> dict[str, object]:
    names = tuple(path.name for path in sorted(root.glob("*.png")))
    _check(names == EXPECTED_NAMES, "extracted image names are not exactly 0000..2799")
    allowed = set(EXPECTED_NAMES) | {"README.md", "LICENSE.md", "MANIFEST.sha256"}
    _check(
        tuple(sorted(path.name for path in root.iterdir())) == tuple(sorted(allowed)),
        "asset directory contains unexpected files or directories",
    )
    manifest_path = root / "MANIFEST.sha256"
    expected_manifest = "".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n"
        for name in EXPECTED_NAMES
    )
    _check(
        manifest_path.read_text(encoding="ascii") == expected_manifest,
        "MANIFEST.sha256 is stale",
    )
    manifest_digest = hashlib.sha256(expected_manifest.encode("ascii")).hexdigest()

    resolver = AssetResolver(root)
    metadata = resolver.verify(names)
    _check(len(metadata) == 2800, f"resolved {len(metadata)}/2800 images")
    _check(
        all(
            item.width_px == EXPECTED_DIMENSIONS[0]
            and item.height_px == EXPECTED_DIMENSIONS[1]
            for item in metadata
        ),
        "source dimensions changed",
    )
    _check(all(item.mode == EXPECTED_MODE for item in metadata), "source mode changed")
    _check(len({item.relative_path for item in metadata}) == 2800, "duplicate resolved filenames")

    manifest = resolver.build_manifest(
        names,
        target_width_px=width,
        target_height_px=height,
        transform="crop",
        background_value=127,
    )
    _check(len(manifest.entries) == 2800, f"manifest contains {len(manifest.entries)}/2800 images")
    _check(manifest.source_manifest_sha256 == manifest_digest, "asset manifest digest mismatch")

    cache_size = 8
    preparer = AssetPreparer(
        resolver,
        width,
        height,
        transform="crop",
        background_value=127,
        cache_size=cache_size,
        manifest=manifest,
    )
    tracemalloc.start()
    for name in names:
        prepared = preparer.prepare(name)
        _check(len(prepared.rgb888) == width * height * 3, f"bad prepared size for {name}")
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metrics = preparer.metrics()
    cache_limit = cache_size * width * height * 3
    _check(metrics["memory_bytes"] <= cache_limit, "prepared image cache exceeded its bound")

    representative = (names[0], names[len(names) // 2], names[-1])
    for name in representative:
        _check(
            preparer.prepare(name).rgb888 == _legacy_crop(root / name, (width, height)),
            f"legacy crop transform mismatch for {name}",
        )
    renderer = ProductionFrameRenderer(
        width,
        height,
        pixel_format,
        photodiode=PhotodiodePatch("bottom_right", 50, 255, 0),
    )
    renderer.prepare_pair(
        preparer.prepare(representative[0]).rgb888,
        preparer.prepare(representative[0]).rgb888,
        asset_key_on="real-asset-on",
        asset_key_off="real-asset-off",
    )
    return {
        "resolved": len(metadata),
        "decoded": metrics["decode_count"],
        "duplicate_filenames": 0,
        "manifest_digest": manifest_digest,
        "manifest_hash": manifest.manifest_hash,
        "source_dimensions": list(EXPECTED_DIMENSIONS),
        "source_mode": EXPECTED_MODE,
        "target_dimensions": [width, height],
        "pixel_format": pixel_format,
        "transform": "crop",
        "background_gray": 127,
        "representative_transform_check": list(representative),
        "prepared_cache": metrics,
        "prepared_cache_bound_bytes": cache_limit,
        "tracemalloc_peak_bytes": peak_bytes,
    }


def _repository_commit() -> str:
    if value := os.environ.get("RPI_VSTIM_SOURCE_COMMIT"):
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=Path(__file__).parents[1]
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def show_subset(
    config: Config,
    root: Path,
    names: tuple[str, ...],
    *,
    frames: int,
    gray_frames: int,
    session_root: Path,
    binary: Path | None,
) -> dict[str, object]:
    resolver = AssetResolver(root)
    manifest = resolver.build_manifest(
        names,
        target_width_px=config.display.width_px,
        target_height_px=config.display.height_px,
        transform="crop",
        background_value=127,
    )
    preparer = AssetPreparer(
        resolver,
        config.display.width_px,
        config.display.height_px,
        transform="crop",
        background_value=127,
        cache_size=8,
        manifest=manifest,
    )
    selected = [
        {"filename": name, "sha256": manifest.entry(name).sha256}
        for name in names
    ]
    session_root.mkdir(parents=True, exist_ok=True)
    provenance = {
        "schema_version": 1,
        "repository_commit": _repository_commit(),
        "asset_manifest_digest": manifest.source_manifest_sha256,
        "selected_image_filenames": list(names),
        "selected_image_identities": selected,
        "display": {
            "connector": config.display.stimulus_connector,
            "width_px": config.display.width_px,
            "height_px": config.display.height_px,
            "pixel_format": config.display.pixel_format,
            "transform": "crop",
            "background_gray": 127,
            "photodiode": config.photodiode.__dict__,
        },
    }
    (session_root / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    display = KmsDisplayBackend(
        native_binary=binary,
        use_lease=True,
        photodiode=PhotodiodePatch(
            config.photodiode.corner,
            config.photodiode.size_px,
            config.photodiode.on_value,
            config.photodiode.off_value,
        ),
    )
    epochs = []
    frame_count = 0

    def stream_frames() -> Iterator[DisplaySequenceFrame]:
        nonlocal frame_count
        if display.renderer is None:
            raise RuntimeError("KMS renderer was not initialized")
        gray_rgb = bytes((127,)) * (config.display.width_px * config.display.height_px * 3)

        def epoch(
            event_id: str,
            sequence_id: str,
            asset_key: str,
            payload: bytes,
            state: str,
            count: int,
        ) -> Iterator[DisplaySequenceFrame]:
            nonlocal frame_count
            epochs.append({
                "event_id": event_id,
                "sequence_id": sequence_id,
                "asset_key": asset_key,
                "start_frame": frame_count,
                "frame_count": count,
                "photodiode_state": state,
            })
            for _ in range(count):
                metadata = DisplaySequenceMetadata(
                    logical_frame_index=frame_count,
                    event_id=event_id,
                    sequence_id=sequence_id,
                    asset_key=asset_key,
                    photodiode_state=state,
                    payload_size=len(payload),
                    producer_sequence=frame_count,
                )
                yield DisplaySequenceFrame(metadata, payload)
                frame_count += 1

        gray = display.renderer.prepare_payload(
            gray_rgb,
            photodiode_state="off",
            asset_key="gray:127",
        )
        yield from epoch("initial-gray", "initial-gray", "gray:127", gray, "off", gray_frames)
        for index, name in enumerate(names):
            prepared = preparer.prepare(name)
            payload = display.renderer.prepare_payload(
                prepared.rgb888,
                photodiode_state="on",
                asset_key=f"{name}:on",
            )
            yield from epoch(name, name, name, payload, "on", frames)
            if index < len(names) - 1:
                yield from epoch(
                    f"iti-{index + 1}",
                    f"iti-{index + 1}",
                    "gray:127",
                    gray,
                    "off",
                    gray_frames,
                )
        yield from epoch("final-gray", "final-gray", "gray:127", gray, "off", gray_frames)

    try:
        display.open(config.display)
        result = display.present_sequence(stream_frames())
    finally:
        display.close()
    result["epochs"] = epochs
    result["epoch_count"] = len(epochs)
    result["frame_state_count"] = frame_count
    payload = {
        "session_root": str(session_root),
        "selected_images": selected,
        "display_results": [result],
    }
    (session_root / "display_results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--pixel-format", choices=("RGB565", "XRGB8888"), default="RGB565")
    parser.add_argument(
        "--display", action="store_true", help="show a short subset on the configured KMS display"
    )
    parser.add_argument(
        "--session-root", type=Path, default=Path("/tmp/rpi-vstim-real-natural-validation")
    )
    parser.add_argument("--indices", default="0,700,1400,2100,2799")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--gray-frames", type=int, default=12)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    config = load_config(args.config) if args.config else Config()
    root = args.asset_root or config.paths.asset_root
    width = args.width or (config.display.width_px if args.config else DEFAULT_DISPLAY_SIZE[0])
    height = args.height or (config.display.height_px if args.config else DEFAULT_DISPLAY_SIZE[1])
    archive_report = inspect_archive(args.archive) if args.archive else None
    if args.display:
        if not args.config:
            parser.error("--display requires --config")
        indices = tuple(int(value) for value in args.indices.split(","))
        names = tuple(EXPECTED_NAMES[index] for index in indices)
        report = {
            "asset_root": str(root.resolve()),
            "archive": archive_report,
            "display_session": show_subset(
                config,
                root,
                names,
                frames=args.frames,
                gray_frames=args.gray_frames,
                session_root=args.session_root,
                binary=args.binary,
            ),
        }
    else:
        report = validate_assets(root, width=width, height=height, pixel_format=args.pixel_format)
        report["asset_root"] = str(root.resolve())
        report["archive"] = archive_report
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
