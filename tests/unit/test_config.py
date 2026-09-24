from dataclasses import replace
from pathlib import Path

import pytest

from rpi_vstim.core.config import Config, ConfigError, config_from_mapping, load_config


def test_example_toml_loads_and_preserves_sections():
    config = load_config(Path("config/system.example.toml"))
    assert config.display.backend == "kms"
    assert config.hardware.reward_pin_bcm == 19
    assert config.telemetry.port == 5055
    assert config.protocol.name == "natural-images"


def test_duplicate_gpio_pins_are_rejected():
    with pytest.raises(ConfigError, match="unique"):
        config_from_mapping({"gpio": {"reward_pin_bcm": 19, "suction_pin_bcm": 19}})


def test_enabled_telemetry_requires_host():
    with pytest.raises(ConfigError, match="telemetry host"):
        config_from_mapping({"telemetry": {"enabled": True}})


def test_experimental_mode_rejects_simulation():
    config = replace(Config(), session=replace(Config().session, experimental=True, simulation=True))
    with pytest.raises(ConfigError, match="simulation"):
        config.validate()

