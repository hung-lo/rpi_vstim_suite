"""Hardware-free production-preflight report generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from .assets import AssetResolver, build_selected_asset_manifest
from .config import Config
from .resource_budget import ResourceBudgetInputs, estimate_budget
from .runtime import build_simulation_plan
from .storage import preflight_storage


def build_dry_run_report(
    config: Config,
    *,
    protocol_name: str | None = None,
    seed: int = 0,
) -> dict[str, object]:
    protocol = protocol_name or config.protocol.name
    if protocol != config.protocol.name:
        config = replace(config, protocol=replace(config.protocol, name=protocol))
    config.validate()
    with TemporaryDirectory(prefix="rpi-vstim-preflight-") as scratch:
        plan_config = replace(config, paths=replace(config.paths, output_root=Path(scratch)))
        plan = build_simulation_plan(plan_config, protocol_name=protocol, seed=seed)
    selected = tuple(
        str(event.metadata["image"])
        for event in plan.events
        if event.kind == "image"
    )
    manifest = None
    asset_status = "deferred: configured asset root is unavailable"
    if config.paths.asset_root.is_dir() and selected:
        resolver = AssetResolver(config.paths.asset_root)
        manifest = build_selected_asset_manifest(
            plan,
            resolver,
            target_width_px=config.display.width_px,
            target_height_px=config.display.height_px,
            transform=plan.metadata.get("asset_transform", "fit_pad"),
            background_value=int(plan.metadata.get("background_gray", 127)),
        )
        asset_status = "ready"
    storage = preflight_storage(
        config.paths.output_root,
        require_mount=False,
        allow_test_path=True,
        estimated_required_bytes=max(1, plan.total_frames * config.display.width_px),
    )
    budget = estimate_budget(
        ResourceBudgetInputs(
            config.display.width_px,
            config.display.height_px,
            config.display.pixel_format,
            camera_count=len(config.cameras.devices),
            asset_manifest_entries=len(manifest.entries) if manifest else 0,
        )
    )
    config_digest = hashlib.sha256(
        json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    asset_manifest_value = manifest.as_dict() if manifest else None
    asset_manifest_digest = manifest.manifest_hash if manifest else None
    return {
        "schema_version": 1,
        "hardware_access": False,
        "protocol": protocol,
        "seed": seed,
        "config_digest": config_digest,
        "plan": {
            "event_count": len(plan.events),
            "total_frames": plan.total_frames,
            "estimated_duration_s": plan.total_frames / config.display.refresh_hz,
            "selected_image_occurrences": len(selected),
        },
        "asset_status": asset_status,
        "asset_manifest": asset_manifest_value,
        "asset_manifest_digest": asset_manifest_digest,
        "resource_budget": budget.as_dict(),
        "storage": storage.as_dict(),
        "camera_requirements": [
            {
                "id": camera.id,
                "role": camera.role,
                "required": camera.required,
                "stable_identity": camera.stable_device_identifier,
                "expected_family": camera.expected_family,
            }
            for camera in config.cameras.devices
        ],
        "display_requirement": config.as_dict()["display"],
        "production_root_requirement": {
            "path": str(config.paths.output_root),
            "mount_required_for_hardware": True,
            "sd_card_is_not_accepted": True,
        },
        "hardware_gates_not_exercised": [
            "DRM/KMS acquisition",
            "camera capture and identity negotiation",
            "SSD identity and sustained writes",
            "GPIO/reward/lick actuation",
            "photodiode validation",
        ],
    }
