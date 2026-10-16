#!/usr/bin/env python3
"""Run paired deterministic plan/asset-manifest checks across varied cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from rpi_vstim.core.assets import AssetResolver, build_selected_asset_manifest
from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.runtime import build_simulation_plan
from rpi_vstim.core.virtual_rig import _write_virtual_assets


PROTOCOLS = ("natural-images", "reward-conditioning", "spout-training", "drifting-gratings", "retinotopy")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def run(cases: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rpi-vstim-repro-campaign-") as temporary:
        asset_root = Path(temporary) / "assets"
        _write_virtual_assets(asset_root, "natural-images")
        _write_virtual_assets(asset_root, "reward-conditioning")
        checked = 0
        protocol_counts = {name: 0 for name in PROTOCOLS}
        last_plan_digest = ""
        last_asset_digest = ""
        for index in range(cases):
            protocol = PROTOCOLS[index % len(PROTOCOLS)]
            camera_mode = "optional-failure" if index % 7 == 0 else "normal"
            cache_size = 2 + index % 7
            transport_capacity = 2 + index % 5
            config = config_from_mapping(
                {
                    "paths": {"output_root": Path(temporary) / "output", "asset_root": asset_root},
                    "protocol": {"name": protocol, "version": "software-groundwork"},
                    "cameras": {
                        "devices": [
                            {"id": "face", "role": "face", "required": True, "device": "face"},
                            {"id": "behavior", "role": "behavior", "device": "behavior"},
                        ]
                    },
                }
            )
            first = build_simulation_plan(config, protocol_name=protocol, seed=index)
            second = build_simulation_plan(config, protocol_name=protocol, seed=index)
            if first.stable_json() != second.stable_json():
                raise AssertionError(f"plan mismatch at seed {index}")
            resolver = AssetResolver(asset_root)
            first_manifest = build_selected_asset_manifest(
                first,
                resolver,
                target_width_px=config.display.width_px,
                target_height_px=config.display.height_px,
                transform=first.metadata.get("asset_transform", "fit_pad"),
            )
            second_manifest = build_selected_asset_manifest(
                second,
                AssetResolver(asset_root),
                target_width_px=config.display.width_px,
                target_height_px=config.display.height_px,
                transform=second.metadata.get("asset_transform", "fit_pad"),
            )
            if first_manifest.manifest_hash != second_manifest.manifest_hash:
                raise AssertionError(f"asset manifest mismatch at seed {index}")
            last_plan_digest = _digest(first.stable_json())
            last_asset_digest = first_manifest.manifest_hash
            checked += 1
            protocol_counts[protocol] += 1
            _ = (camera_mode, cache_size, transport_capacity)
        return {
            "paired_cases": checked,
            "protocol_counts": protocol_counts,
            "last_plan_digest": last_plan_digest,
            "last_asset_manifest_digest": last_asset_digest,
            "deterministic": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=500)
    args = parser.parse_args()
    if args.cases < 1:
        parser.error("cases must be positive")
    print(json.dumps(run(args.cases), sort_keys=True))


if __name__ == "__main__":
    main()
