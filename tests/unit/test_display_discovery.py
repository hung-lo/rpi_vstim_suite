from pathlib import Path

import pytest

from rpi_vstim.core.config import ConfigError, DisplayConfig, config_from_mapping
from rpi_vstim.display.diagnostics import probe_config
from rpi_vstim.display.discovery import (
    DisplaySelectionError,
    parse_modetest_connectors,
    select_display,
)

FIXTURE = Path("tests/fixtures/modetest_dual_hdmi.txt").read_text()


def test_parse_and_select_explicit_stimulus_connector():
    inventory = parse_modetest_connectors(FIXTURE)
    config = DisplayConfig(
        stimulus_connector="HDMI-A-1",
        preview_connector="HDMI-A-2",
        width_px=1024,
        height_px=600,
        refresh_hz=59.82,
    )
    selection = select_display(inventory, config)
    assert selection.connector.name == "HDMI-A-1"
    assert selection.mode.preferred


def test_preview_can_be_disabled_and_wrong_mode_fails():
    inventory = parse_modetest_connectors(FIXTURE)
    config = DisplayConfig(
        stimulus_connector="HDMI-A-2",
        preview_connector=None,
        width_px=1280,
        height_px=720,
        refresh_hz=60.0,
    )
    with pytest.raises(DisplaySelectionError, match="disabled"):
        select_display(inventory, config, role="preview")
    with pytest.raises(DisplaySelectionError, match="unsupported"):
        select_display(inventory, config, role="stimulus")


def test_non_exact_refresh_selects_nearest_supported_mode():
    inventory = parse_modetest_connectors(FIXTURE)
    config = DisplayConfig(
        width_px=1024,
        height_px=600,
        refresh_hz=60.0,
        require_exact_refresh=False,
    )
    assert select_display(inventory, config).mode.refresh_hz == 59.82


def test_disconnected_or_missing_connector_does_not_fallback():
    inventory = parse_modetest_connectors(FIXTURE.replace("connected\tHDMI-A-1", "disconnected\tHDMI-A-1"))
    config = DisplayConfig(width_px=1024, height_px=600, refresh_hz=59.82)
    with pytest.raises(DisplaySelectionError, match="not connected"):
        select_display(inventory, config)
    with pytest.raises(DisplaySelectionError, match="missing"):
        select_display(
            inventory,
            config_from_mapping({"display": {"stimulus_connector": "HDMI-X"}}).display,
        )


def test_legacy_connector_alias_and_role_validation():
    config = config_from_mapping(
        {"display": {"connector": "HDMI-A-1", "preview_connector": ""}}
    )
    assert config.display.stimulus_connector == "HDMI-A-1"
    assert config.display.preview_connector is None
    with pytest.raises(ConfigError, match="must differ"):
        config_from_mapping({"display": {"stimulus_connector": "HDMI-A-1", "preview_connector": "HDMI-A-1"}})


def test_probe_config_keeps_preview_separate():
    config = DisplayConfig(
        stimulus_connector="HDMI-A-1",
        preview_connector="HDMI-A-2",
        width_px=1024,
        height_px=600,
        refresh_hz=59.82,
    )
    result = probe_config(config, command=("cat", "tests/fixtures/modetest_dual_hdmi.txt"))
    assert result["stimulus"]["connector"] == "HDMI-A-1"
    assert result["preview"]["connector"] == "HDMI-A-2"
