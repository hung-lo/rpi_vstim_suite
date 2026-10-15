import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from rpi_vstim.cli import main
from rpi_vstim.core.config import ConfigError, config_from_mapping, load_config
from rpi_vstim.doctor import inspect_machine
from rpi_vstim.session import new_session


def test_profiles_separate_current_rig_sound_pins_from_generic_profiles():
    root = Path(__file__).resolve().parents[2]
    generic = load_config(root / "config/rigs/pi5_default.toml")
    simulation = load_config(root / "config/rigs/simulation.toml")
    current_rig = load_config(root / "config/rigs/pi5_natural_image_demo.example.toml")
    assert generic.display.backend == simulation.display.backend == "fake"
    assert generic.hardware.reward_pin_bcm == simulation.hardware.reward_pin_bcm == -1
    assert generic.operator_controls.bait_button_gpio == -1
    assert (generic.hardware.sound_trigger_1_pin_bcm, generic.hardware.sound_trigger_2_pin_bcm) == (-1, -1)
    assert (simulation.hardware.sound_trigger_1_pin_bcm, simulation.hardware.sound_trigger_2_pin_bcm) == (-1, -1)
    with pytest.raises(ConfigError, match="reward GPIO is unassigned"):
        generic.hardware.output_line("reward")
    assert "/mnt/behavbox_ssd" not in str(generic.paths.output_root)
    assert current_rig.hardware.lick_pin_bcm == 26
    assert current_rig.paths.output_root == Path("/mnt/behavbox_ssd/sessions")
    assert (current_rig.hardware.sound_trigger_1_pin_bcm,
            current_rig.hardware.sound_trigger_2_pin_bcm) == (23, 24)
    assert current_rig.operator_controls.bait_button_gpio == -1
    assert not current_rig.operator_controls.bait_button_enabled
    for path in (
        "config/rigs/pi5_dual_display_preflight.example.toml",
        "config/rigs/pi5_dual_display_provisional.example.toml",
    ):
        profile = load_config(root / path)
        assert (profile.hardware.sound_trigger_1_pin_bcm,
                profile.hardware.sound_trigger_2_pin_bcm) == (23, 24)
        assert profile.operator_controls.bait_button_gpio == -1
    with pytest.raises(ConfigError, match="BCM GPIO9 is reserved for IRIG output"):
        config_from_mapping({"hardware": {"ttl_pin_bcm": 9}})
    with pytest.raises(ConfigError, match="paths must not be empty"):
        config_from_mapping({"paths": {"output_root": ""}})


def test_sound_pin_ownership_conflicts_are_rejected():
    assert config_from_mapping({"hardware": {"sound_trigger_1_pin_bcm": 23}}).hardware.sound_trigger_1_pin_bcm == 23
    with pytest.raises(ConfigError, match="GPIO pins must be unique"):
        config_from_mapping({"hardware": {"sound_trigger_1_pin_bcm": 23},
                             "operator_controls": {"bait_button_gpio": 23}})
    with pytest.raises(ConfigError, match="GPIO pins must be unique"):
        config_from_mapping({"hardware": {"sound_trigger_2_pin_bcm": 24, "ttl_pin_bcm": 24}})
    with pytest.raises(ConfigError, match="GPIO23.*sound_trigger_1"):
        config_from_mapping({"hardware": {"reward_pin_bcm": 23}})
    with pytest.raises(ConfigError, match="GPIO24.*sound_trigger_2"):
        config_from_mapping({"hardware": {"reward_pin_bcm": 24}})


def test_doctor_read_only_with_missing_optional_services(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("rpi_vstim.doctor._command", lambda *args: "")
    monkeypatch.setattr("rpi_vstim.doctor.shutil.which", lambda name: None)
    config = replace(load_config(), paths=replace(load_config().paths, output_root=tmp_path))
    before = set(tmp_path.iterdir())
    report = inspect_machine(config)
    assert report["hardware_access"] is False
    assert report["neurokairos"] == {"installed": False, "active": False}
    assert report["chrony"] == {"installed": False, "active": False}
    assert set(tmp_path.iterdir()) == before
    profile = tmp_path / "profile.toml"
    profile.write_text(f'[paths]\noutput_root = "{tmp_path}"\n', encoding="utf-8")
    assert main(["doctor", "--config", str(profile), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["storage"]["exists"] is True


def test_public_session_api_finalizes_with_no_hardware(tmp_path):
    config = replace(load_config(), paths=replace(load_config().paths, output_root=tmp_path))
    session = new_session(config, session_id="example")
    session.write_initial_outputs()
    session.record_event("EXAMPLE")
    session.update_status("COMPLETE", lifecycle="COMPLETE")
    session.close()
    assert json.loads((tmp_path / "example/final_status.json").read_text())["status"] == "COMPLETE"


def test_examples_run_with_fake_services(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2] / "examples"
    for name, args in (
        ("minimal_display", []),
        ("image_sequence", []),
        ("minimal_session", ["--output-root", str(tmp_path), "--display", "--cameras"]),
    ):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(sys, "argv", [name, *args])
        module.main()
    assert (tmp_path / "minimal-session/final_status.json").is_file()
    assert (tmp_path / "minimal-session/camera_manifest.json").is_file()
