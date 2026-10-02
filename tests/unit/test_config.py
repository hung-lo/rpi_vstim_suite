from dataclasses import replace
from pathlib import Path

import pytest

import rpi_vstim.core.config as config_module
from rpi_vstim.cli import main
from rpi_vstim.core.config import Config, ConfigError, config_from_mapping, load_config


def test_example_toml_loads_and_preserves_sections():
    config = load_config(Path("config/system.example.toml"))
    assert config.display.backend == "fake"
    assert config.display.ownership == ""
    assert config.display.stimulus_connector == ""
    assert config.display.preview_connector is None
    assert config.hardware.reward_pin_bcm == 19
    assert config.telemetry.port == 5055
    assert config.protocol.name == "natural-images"


def test_pi5_provisional_gpio_roles_are_configured_without_polarity_claims():
    config = load_config(Path("config/rigs/pi5_dual_display_provisional.example.toml"))
    assert config.hardware.backend == "lgpio"
    assert config.hardware.output_line("reward").bcm_pin == 19
    assert config.hardware.output_line("vacuum").bcm_pin == 25
    assert config.hardware.output_line("reward").active_level is None
    assert config.hardware.output_line("vacuum").active_level is None


def test_load_config_resolves_relative_paths_from_config_file(tmp_path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    config_path = tmp_path / "config" / "natural.toml"
    config_path.parent.mkdir()
    config_path.write_text('[paths]\nasset_root = "../assets"\n')

    assert load_config(config_path).paths.asset_root == asset_root.resolve()


def test_default_display_is_neutral_for_simulation():
    assert Config().display.backend == "fake"
    assert Config().display.ownership == ""
    assert Config().display.stimulus_connector == ""
    assert Config().display.preview_connector is None


def test_hardware_display_requires_an_explicit_connector():
    with pytest.raises(ConfigError, match="required for the KMS backend"):
        config_from_mapping({"display": {"backend": "kms", "ownership": "direct"}})


def test_hardware_display_requires_explicit_ownership():
    with pytest.raises(ConfigError, match="ownership is required"):
        config_from_mapping({"display": {"backend": "kms", "stimulus_connector": "HDMI-A-2"}})


def test_display_ownership_is_validated():
    with pytest.raises(ConfigError, match="ownership"):
        config_from_mapping({"display": {"ownership": "compositor"}})


def test_duplicate_gpio_pins_are_rejected():
    with pytest.raises(ConfigError, match="unique"):
        config_from_mapping({"gpio": {"reward_pin_bcm": 19, "suction_pin_bcm": 19}})


def test_enabled_telemetry_requires_host():
    with pytest.raises(ConfigError, match="telemetry host"):
        config_from_mapping({"telemetry": {"enabled": True}})


def test_required_telemetry_must_be_enabled():
    with pytest.raises(ConfigError, match="required.*enabled"):
        config_from_mapping({"telemetry": {"required": True}})


def test_unknown_hardware_backend_is_rejected():
    with pytest.raises(ConfigError, match="unsupported hardware backend"):
        config_from_mapping({"hardware": {"backend": "gpiozero"}})


def test_negative_hardware_chip_is_rejected():
    with pytest.raises(ConfigError, match="chip"):
        config_from_mapping({"hardware": {"chip": -1}})


def test_unknown_camera_backend_is_rejected():
    with pytest.raises(ConfigError, match="unsupported camera backend"):
        config_from_mapping(
            {"cameras": {"devices": [{"id": "face", "role": "face", "backend": "ssh"}]}}
        )


def test_experimental_mode_rejects_simulation():
    config = replace(Config(), session=replace(Config().session, experimental=True, simulation=True))
    with pytest.raises(ConfigError, match="simulation"):
        config.validate()


def test_experimental_config_parsing_does_not_require_pi_paths():
    config = config_from_mapping(
        {
            "paths": {
                "output_root": "/missing/output",
                "cache_root": "/missing/cache",
                "asset_root": "/missing/assets",
                "reward_state_root": "/missing/state",
            },
            "display": {
                "backend": "kms",
                "ownership": "direct",
                "stimulus_connector": "HDMI-A-2",
                "preview_connector": "HDMI-A-1",
                "calibration_id": "ol7",
            },
            "hardware": {"backend": "lgpio"},
            "session": {"experimental": True, "simulation": False},
        }
    )
    config.validate()


def test_explicit_experimental_validation_checks_paths():
    config = config_from_mapping(
        {
            "display": {
                "backend": "kms",
                "ownership": "direct",
                "stimulus_connector": "HDMI-A-2",
                "preview_connector": "HDMI-A-1",
                "calibration_id": "ol7",
            },
            "hardware": {"backend": "lgpio"},
            "session": {"experimental": True, "simulation": False},
        }
    )
    with pytest.raises(ConfigError, match="existing writable directory"):
        config.validate(require_paths=True)


def test_path_validation_uses_readability_for_assets(tmp_path, monkeypatch):
    paths = {
        "output_root": tmp_path / "output",
        "cache_root": tmp_path / "cache",
        "asset_root": tmp_path / "assets",
        "reward_state_root": tmp_path / "state",
    }
    for path in paths.values():
        path.mkdir()
    config = config_from_mapping(
        {
            "paths": paths,
            "display": {
                "backend": "kms",
                "ownership": "direct",
                "stimulus_connector": "HDMI-A-2",
                "preview_connector": "HDMI-A-1",
                "calibration_id": "ol7",
            },
            "hardware": {"backend": "lgpio"},
            "session": {"experimental": True, "simulation": False},
        }
    )
    modes = {}

    def fake_access(path, mode):
        modes[Path(path).name] = mode
        return True

    monkeypatch.setattr(config_module.os, "access", fake_access)
    config.validate(require_paths=True)
    assert modes["assets"] == config_module.os.R_OK
    assert modes["output"] == config_module.os.W_OK
    assert modes["cache"] == config_module.os.W_OK
    assert modes["state"] == config_module.os.W_OK


def test_dual_local_camera_config_parses_stable_identities():
    config = config_from_mapping(
        {
            "cameras": {
                "enabled_by_default": True,
                "devices": [
                    {
                        "id": "face",
                        "role": "face",
                        "backend": "v4l2",
                        "stable_device_identifier": "usb-face-serial",
                    },
                    {
                        "id": "behavior",
                        "role": "behavior",
                        "backend": "auto",
                        "device": "platform-camera-1",
                    },
                ],
            }
        }
    )
    assert [camera.id for camera in config.cameras.devices] == ["face", "behavior"]
    assert [camera.role for camera in config.cameras.devices] == ["face", "behavior"]
    assert config.cameras.devices[0].stable_device_identifier == "usb-face-serial"
    assert config.cameras.devices[0].output_naming_policy == "capture"


@pytest.mark.parametrize(
    ("field", "message"),
    [("id", "IDs"), ("role", "roles"), ("device", "devices")],
)
def test_duplicate_camera_bindings_are_rejected(field, message):
    first = {"id": "face", "role": "face", "device": "physical-face"}
    second = {"id": "behavior", "role": "behavior", "device": "physical-behavior"}
    if field == "id":
        second["id"] = first["id"]
    elif field == "role":
        second["role"] = first["role"]
    else:
        second["device"] = first["device"]
    with pytest.raises(ConfigError, match=message):
        config_from_mapping({"cameras": {"devices": [first, second]}})


def test_required_camera_needs_stable_identity_in_experimental_mode():
    with pytest.raises(ConfigError, match="stable device identity"):
        config_from_mapping(
            {
                "cameras": {"devices": [{"id": "face", "role": "face", "required": True}]},
                "display": {
                    "backend": "kms",
                    "ownership": "direct",
                    "stimulus_connector": "HDMI-A-2",
                    "preview_connector": "HDMI-A-1",
                    "calibration_id": "ol7",
                },
                "hardware": {"backend": "lgpio"},
                "session": {"experimental": True, "simulation": False},
            }
        )


def test_experimental_cli_requires_experimental_session(tmp_path, capsys):
    for name in ("output", "cache", "assets", "state"):
        (tmp_path / name).mkdir()
    config_path = tmp_path / "simulation.toml"
    config_path.write_text(
        "\n".join(
            [
                "[paths]",
                f'output_root = "{tmp_path / "output"}"',
                f'cache_root = "{tmp_path / "cache"}"',
                f'asset_root = "{tmp_path / "assets"}"',
                f'reward_state_root = "{tmp_path / "state"}"',
                "[session]",
                "experimental = false",
                "simulation = true",
            ]
        )
        + "\n"
    )
    assert main(["config", "validate", str(config_path), "--experimental"]) == 2
    assert "session.experimental=true" in capsys.readouterr().err
