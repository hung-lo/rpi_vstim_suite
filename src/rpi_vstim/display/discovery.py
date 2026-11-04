"""Hardware-independent DRM connector and mode discovery helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from rpi_vstim.core.config import DisplayConfig


class DisplaySelectionError(ValueError):
    """Raised when an explicit display role cannot be resolved safely."""


@dataclass(frozen=True)
class DisplayMode:
    name: str
    width_px: int
    height_px: int
    refresh_hz: float
    preferred: bool = False


@dataclass(frozen=True)
class ConnectorInfo:
    name: str
    status: str
    modes: tuple[DisplayMode, ...]


@dataclass(frozen=True)
class DisplayInventory:
    connectors: tuple[ConnectorInfo, ...]

    def connector(self, name: str) -> ConnectorInfo:
        for connector in self.connectors:
            if connector.name == name:
                return connector
        raise DisplaySelectionError(f"configured connector is missing: {name}")


@dataclass(frozen=True)
class DisplaySelection:
    role: str
    connector: ConnectorInfo
    mode: DisplayMode


_CONNECTOR = re.compile(r"^\s*\d+\s+\d+\s+(connected|disconnected)\s+(\S+)")
_MODE = re.compile(r"^\s*#\d+\s+(\d+x\d+)\s+([0-9]+(?:\.[0-9]+)?)\s+.*?type:\s*(.*)$")


def parse_modetest_connectors(text: str) -> DisplayInventory:
    """Parse `modetest -c` output without assuming card or connector numbers."""
    connectors: list[ConnectorInfo] = []
    current_name: str | None = None
    current_status = ""
    current_modes: list[DisplayMode] = []
    for line in text.splitlines():
        match = _CONNECTOR.match(line)
        if match:
            if current_name is not None:
                connectors.append(ConnectorInfo(current_name, current_status, tuple(current_modes)))
            current_status, current_name = match.groups()
            current_modes = []
            continue
        if current_name is None:
            continue
        match = _MODE.match(line)
        if match:
            size, refresh, mode_type = match.groups()
            width, height = (int(value) for value in size.split("x"))
            current_modes.append(
                DisplayMode(
                    size,
                    width,
                    height,
                    float(refresh),
                    "preferred" in mode_type.split(","),
                )
            )
    if current_name is not None:
        connectors.append(ConnectorInfo(current_name, current_status, tuple(current_modes)))
    return DisplayInventory(tuple(connectors))


def select_display(
    inventory: DisplayInventory,
    config: DisplayConfig,
    *,
    role: str = "stimulus",
) -> DisplaySelection:
    """Resolve an explicit role and its configured stimulus mode."""
    connector = select_connector(inventory, config, role=role)
    if role == "stimulus" and config.mode_selection_policy == "preferred":
        candidates = [mode for mode in connector.modes if mode.refresh_hz > 0]
        if not candidates:
            raise DisplaySelectionError(f"connected display has no usable modes: {connector.name}")
        mode = min(
            candidates,
            key=lambda value: (
                not value.preferred,
                -(value.width_px * value.height_px),
                -value.refresh_hz,
                value.width_px,
                value.height_px,
                value.name,
            ),
        )
        return DisplaySelection(role, connector, mode)
    candidates = [
        mode
        for mode in connector.modes
        if mode.width_px == config.width_px and mode.height_px == config.height_px
    ]
    if not candidates:
        raise DisplaySelectionError(
            f"requested mode is unsupported on {connector.name}: "
            f"{config.width_px}x{config.height_px}"
        )
    selected = min(candidates, key=lambda mode: abs(mode.refresh_hz - config.refresh_hz))
    difference = abs(selected.refresh_hz - config.refresh_hz)
    if config.require_exact_refresh and difference > config.refresh_tolerance_hz:
        raise DisplaySelectionError(
            f"requested refresh is unavailable on {connector.name}: "
            f"requested {config.refresh_hz:g}Hz, nearest {selected.refresh_hz:g}Hz"
        )
    return DisplaySelection(role, connector, selected)


def select_connector(
    inventory: DisplayInventory,
    config: DisplayConfig,
    *,
    role: str = "preview",
) -> ConnectorInfo:
    """Resolve role identity/status without imposing stimulus mode constraints."""
    connector_name = config.stimulus_connector if role == "stimulus" else config.preview_connector
    if connector_name is None:
        raise DisplaySelectionError(f"{role} display is disabled")
    if role == "stimulus" and not connector_name:
        if config.selection_policy != "auto_single":
            raise DisplaySelectionError("stimulus display connector is not configured")
        candidates = connected_hdmi_connectors(inventory)
        if not candidates:
            raise DisplaySelectionError(
                "no connected HDMI display found; connect an HDMI monitor or configure a connector"
            )
        if len(candidates) != 1:
            names = ", ".join(item.name for item in candidates)
            raise DisplaySelectionError(
                f"Multiple displays detected: {names}. Specify --stimulus-connector HDMI-A-X "
                "or configure stimulus_connector in your TOML file."
            )
        return candidates[0]
    connector = inventory.connector(connector_name)
    if connector.status != "connected":
        raise DisplaySelectionError(
            f"configured {role} connector is not connected: {connector.name} ({connector.status})"
        )
    return connector


def resolve_display_config(
    inventory: DisplayInventory,
    config: DisplayConfig,
    *,
    selection_source: str | None = None,
) -> tuple[DisplayConfig, dict[str, object]]:
    """Freeze an auto or configured choice into explicit dimensions and refresh."""
    selection = select_display(inventory, config, role="stimulus")
    source = selection_source or ("config" if config.stimulus_connector else "auto")
    resolved = replace(
        config,
        selection_policy="explicit",
        mode_selection_policy="configured",
        stimulus_connector=selection.connector.name,
        width_px=selection.mode.width_px,
        height_px=selection.mode.height_px,
        refresh_hz=selection.mode.refresh_hz,
        require_exact_refresh=True,
        # modetest prints two decimal places; keep the native mode match within rounding error.
        refresh_tolerance_hz=min(config.refresh_tolerance_hz, 0.005),
    )
    return resolved, {
        "connector": selection.connector.name,
        "width_px": selection.mode.width_px,
        "height_px": selection.mode.height_px,
        "selected_drm_mode": f"{selection.mode.name}@{selection.mode.refresh_hz:g}",
        "nominal_refresh_hz": selection.mode.refresh_hz,
        "selection_policy": config.selection_policy,
        "selection_source": source,
        "connector_selection": {
            "config": "configured",
            "cli": "cli",
            "interactive": "interactive",
            "auto": "single_connected_hdmi",
        }[source],
        "mode_selection_policy": config.mode_selection_policy,
        "ownership_mode": config.ownership,
    }


def connected_connectors(inventory: DisplayInventory) -> tuple[ConnectorInfo, ...]:
    return tuple(connector for connector in inventory.connectors if connector.status == "connected")


def connected_hdmi_connectors(inventory: DisplayInventory) -> tuple[ConnectorInfo, ...]:
    return tuple(
        connector
        for connector in connected_connectors(inventory)
        if connector.name.upper().startswith("HDMI")
    )


def inventory_from_connectors(connectors: Iterable[ConnectorInfo]) -> DisplayInventory:
    return DisplayInventory(tuple(connectors))
