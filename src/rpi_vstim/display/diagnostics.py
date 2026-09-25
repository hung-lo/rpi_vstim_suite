"""Read-only DRM/KMS discovery through the installed diagnostic tools."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

from rpi_vstim.core.config import DisplayConfig

from .discovery import (
    DisplayInventory,
    DisplaySelection,
    DisplaySelectionError,
    parse_modetest_connectors,
    select_display,
)


class DisplayProbeError(RuntimeError):
    pass


def discover_modetest(
    *,
    command: Sequence[str] = ("modetest", "-M", "vc4", "-c"),
) -> DisplayInventory:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DisplayProbeError(f"display diagnostic command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout).strip()
        raise DisplayProbeError(f"display discovery failed: {detail}") from exc
    inventory = parse_modetest_connectors(result.stdout)
    if not inventory.connectors:
        raise DisplayProbeError("display discovery returned no DRM connectors")
    return inventory


def probe_config(
    config: DisplayConfig,
    *,
    command: Sequence[str] = ("modetest", "-M", "vc4", "-c"),
) -> dict[str, object]:
    inventory = discover_modetest(command=command)
    try:
        stimulus = select_display(inventory, config, role="stimulus")
        preview = (
            None
            if config.preview_connector is None
            else select_display(inventory, config, role="preview")
        )
    except DisplaySelectionError as exc:
        raise DisplayProbeError(str(exc)) from exc
    return {
        "stimulus": _selection_dict(stimulus),
        "preview": None if preview is None else _selection_dict(preview),
    }


def display_probe(config: DisplayConfig | None = None, *, as_json: bool = False) -> str:
    """Return a read-only probe result; useful for the CLI and smoke scripts."""
    result = probe_config(config or DisplayConfig())
    return json.dumps(result, indent=2, sort_keys=True) if as_json else _text_result(result)


def _selection_dict(selection: DisplaySelection) -> dict[str, object]:
    return {
        "connector": selection.connector.name,
        "status": selection.connector.status,
        "mode": selection.mode.name,
        "refresh_hz": selection.mode.refresh_hz,
        "preferred": selection.mode.preferred,
    }


def _text_result(result: dict[str, object]) -> str:
    lines = []
    for role in ("stimulus", "preview"):
        value = result[role]
        if value is None:
            lines.append(f"{role}: disabled")
        else:
            lines.append(
                f"{role}: {value['connector']} {value['mode']}@{value['refresh_hz']:.2f}Hz"
            )
    return "\n".join(lines)
