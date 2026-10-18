from __future__ import annotations

import math
import tomllib
from dataclasses import fields
from pathlib import Path

from rpi_vstim.core.config import ConfigError


def load_protocol_settings(protocol_name: str, path: Path, *, refresh_hz: float, seed: int | None = None):
    from rpi_vstim.protocols.drifting_gratings import (
        DriftingGratingSettings,
        RectangularPatchGeometry,
    )
    from rpi_vstim.protocols.retinotopy import RetinotopySettings

    settings_types = {
        "drifting-gratings": DriftingGratingSettings,
        "retinotopy": RetinotopySettings,
    }
    try:
        settings_type = settings_types[protocol_name]
    except KeyError as exc:
        raise ConfigError(f"unsupported visual-mapping protocol: {protocol_name}") from exc
    try:
        with Path(path).open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot load visual protocol config {path}: {exc}") from exc
    protocol = raw.get("protocol")
    if not isinstance(protocol, dict):
        raise ConfigError("visual protocol config must contain a [protocol] table")
    configured_name = protocol.get("name")
    if configured_name != protocol_name:
        raise ConfigError(f"protocol config names {configured_name!r}, expected {protocol_name!r}")
    values = {key: value for key, value in protocol.items() if key not in {"name", "version"}}
    allowed = {item.name for item in fields(settings_type)}
    unknown = set(values) - allowed
    if unknown:
        raise ConfigError("unknown visual protocol setting(s): " + ", ".join(sorted(unknown)))
    if protocol_name == "drifting-gratings" and isinstance(values.get("rectangular_patch_geometry"), dict):
        try:
            values["rectangular_patch_geometry"] = RectangularPatchGeometry(
                **values["rectangular_patch_geometry"]
            )
        except TypeError as exc:
            raise ConfigError(f"invalid rectangular_patch_geometry: {exc}") from exc
    values["refresh_hz"] = refresh_hz
    if seed is not None:
        values["sequence_seed"] = seed
    try:
        return settings_type(**values)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid {protocol_name} settings: {exc}") from exc


def validate_refresh_rate(config, settings) -> None:
    protocol_refresh_hz = float(settings.refresh_hz)
    display_refresh_hz = float(config.display.refresh_hz)
    if not math.isclose(protocol_refresh_hz, display_refresh_hz, rel_tol=0.0, abs_tol=1e-9):
        raise ConfigError(
            f"protocol refresh_hz ({protocol_refresh_hz:g}) must match configured "
            f"display refresh_hz ({display_refresh_hz:g})"
        )
