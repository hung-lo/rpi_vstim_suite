"""Read-only DRM/KMS discovery through the installed diagnostic tools."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

from rpi_vstim.core.config import DisplayConfig

from .discovery import (
    ConnectorInfo,
    DisplayInventory,
    DisplaySelection,
    DisplaySelectionError,
    parse_modetest_connectors,
    select_connector,
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
            else select_connector(inventory, config, role="preview")
        )
    except DisplaySelectionError as exc:
        raise DisplayProbeError(str(exc)) from exc
    return {
        "stimulus": _selection_dict(stimulus),
        "preview": None if preview is None else _connector_dict(preview),
    }


def display_inventory(
    config: DisplayConfig | None = None,
    *,
    command: Sequence[str] = ("modetest", "-M", "vc4", "-c"),
) -> dict[str, object]:
    """Return the read-only connector and supported-mode inventory."""
    inventory = discover_modetest(command=command)
    configured_selection = None
    if config is not None and (config.stimulus_connector or config.selection_policy == "auto_single"):
        source = "config" if config.stimulus_connector else "auto"
        try:
            configured_selection = {
                **_selection_dict(select_display(inventory, config, role="stimulus")),
                "selection_source": source,
            }
        except DisplaySelectionError as exc:
            configured_selection = {"selection_source": source, "error": str(exc)}
    return {
        "connectors": [
            {
                "connector": connector.name,
                "status": connector.status,
                "modes": [
                    {
                        "mode": mode.name,
                        "width_px": mode.width_px,
                        "height_px": mode.height_px,
                        "refresh_hz": mode.refresh_hz,
                        "preferred": mode.preferred,
                    }
                    for mode in connector.modes
                ],
            }
            for connector in sorted(inventory.connectors, key=lambda value: value.name)
        ],
        "configured_selection": configured_selection,
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
        "width_px": selection.mode.width_px,
        "height_px": selection.mode.height_px,
        "refresh_hz": selection.mode.refresh_hz,
        "preferred": selection.mode.preferred,
    }


def _connector_dict(connector: ConnectorInfo) -> dict[str, object]:
    return {
        "connector": connector.name,
        "status": connector.status,
    }


def _text_result(result: dict[str, object]) -> str:
    lines = []
    for role in ("stimulus", "preview"):
        value = result[role]
        if value is None:
            lines.append(f"{role}: disabled")
        elif "mode" not in value:
            lines.append(f"{role}: {value['connector']} ({value['status']})")
        else:
            lines.append(
                f"{role}: {value['connector']} {value['mode']}@{value['refresh_hz']:g}Hz"
            )
    return "\n".join(lines)


def format_display_inventory(result: dict[str, object]) -> str:
    """Format display inventory for a terminal without acquiring KMS ownership."""
    lines = ["DRM display connectors:"]
    for connector in result["connectors"]:
        lines.append(f"{connector['connector']} ({connector['status']})")
        if not connector["modes"]:
            lines.append("  no modes reported")
        for mode in connector["modes"]:
            preferred = " (preferred)" if mode["preferred"] else ""
            lines.append(
                f"  {mode['width_px']}x{mode['height_px']} @ {mode['refresh_hz']:.2f} Hz"
                f"{preferred}"
            )
    selected = result.get("configured_selection")
    if selected is not None:
        if "error" in selected:
            lines.append(f"Configured stimulus selection unavailable: {selected['error']}")
        else:
            lines.append(
                "Configured stimulus: "
                f"{selected['connector']} {selected['width_px']}x{selected['height_px']} "
                f"@ {selected['refresh_hz']:.2f} Hz ({selected['selection_source']})"
            )
    return "\n".join(lines)
