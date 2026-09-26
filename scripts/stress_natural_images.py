#!/usr/bin/env python3
"""Run a bounded synthetic natural-image preparation campaign on a desktop."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from PIL import Image

from rpi_vstim.core.assets import AssetPreparer, AssetResolver, build_selected_asset_manifest
from rpi_vstim.core.plan import PlannedEvent, SessionPlan, with_frame_offsets
from rpi_vstim.display.renderer import ProductionFrameRenderer
from rpi_vstim.display.sequence import BoundedFrameTransport, NaturalImageFrameSource, PrefetchCoordinator


def build_corpus(root: Path) -> tuple[str, ...]:
    sizes = ((4, 4), (8, 3), (3, 8), (11, 7), (2, 13), (17, 5))
    names = []
    for index, size in enumerate(sizes):
        mode = ("RGB", "L", "RGBA")[index % 3]
        image = Image.new(mode, size, 32 + index * 20)
        path = root / f"asset_{index}.png"
        image.save(path)
        names.append(path.name)
    (root / "duplicate.png").write_bytes((root / "asset_0.png").read_bytes())
    names.append("duplicate.png")
    return tuple(names)


def run(frames: int, cache_size: int, transport_capacity: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-asset-stress-") as temporary:
        root = Path(temporary)
        assets = build_corpus(root)
        events = tuple(
            PlannedEvent(
                f"asset-{index}",
                "image",
                max(1, frames // len(assets)),
                metadata={"image": assets[index % len(assets)]},
            )
            for index in range(len(assets))
        )
        plan = SessionPlan("natural-images", 123, with_frame_offsets(events))
        resolver = AssetResolver(root)
        manifest = build_selected_asset_manifest(
            plan,
            resolver,
            target_width_px=32,
            target_height_px=24,
            transform="crop",
        )
        preparer = AssetPreparer(
            resolver,
            32,
            24,
            transform="crop",
            manifest=manifest,
            cache_size=cache_size,
        )
        renderer = ProductionFrameRenderer(32, 24, "RGB565", cache_size=cache_size)
        source = NaturalImageFrameSource(preparer, renderer)
        coordinator = PrefetchCoordinator(
            source.prepared_frames(plan),
            BoundedFrameTransport(transport_capacity),
            low_watermark=1,
            high_watermark=transport_capacity,
        )
        coordinator.start()
        consumed = 0
        payload_ids: set[int] = set()
        while True:
            frame = coordinator.get(timeout_s=2)
            if frame is None:
                break
            consumed += 1
            payload_ids.add(id(frame.packed))
        coordinator.stop()
        return {
            "logical_frames": consumed,
            "source_file_reads": resolver.source_reads,
            "sha256_calculations": resolver.hash_calculations,
            "decode_count": preparer.metrics()["decode_count"],
            "cache": preparer.metrics(),
            "renderer_payload_allocations": renderer.payload_allocations,
            "prefetch": coordinator.metrics().as_dict(),
            "manifest": manifest.as_dict(),
            "payload_identity_sample_count": len(payload_ids),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=5000)
    parser.add_argument("--cache-size", type=int, default=4)
    parser.add_argument("--transport-capacity", type=int, default=8)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")
    print(json.dumps(run(args.frames, args.cache_size, args.transport_capacity), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
