import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from rpi_vstim import cli
from rpi_vstim.core.config import Config, load_config
from rpi_vstim.core.duration import milliseconds_to_frames, seconds_to_frames
from rpi_vstim.core.natural_image_demo import (
    NaturalImageDemoError,
    build_demo_plan,
    prepare_natural_image_demo,
    run_natural_image_demo,
)
from rpi_vstim.display.discovery import (
    ConnectorInfo,
    DisplayInventory,
    DisplayMode,
    DisplaySelectionError,
    parse_modetest_connectors,
    resolve_display_config,
    select_display,
)
from rpi_vstim.display.diagnostics import display_inventory
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan

FIXTURE = Path("tests/fixtures/modetest_dual_hdmi.txt").read_text()
PORTABLE_CONFIG = Path("config/rigs/pi5_single_screen_display_only.example.toml")


def _auto_display(**overrides):
    values = {
        "backend": "kms",
        "ownership": "lease",
        "selection_policy": "auto_single",
        "mode_selection_policy": "preferred",
        "stimulus_connector": "",
        "preview_connector": None,
    }
    values.update(overrides)
    return replace(Config().display, **values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (FIXTURE.replace("42\t41\tconnected\tHDMI-A-2", "42\t41\tdisconnected\tHDMI-A-2"), "HDMI-A-1"),
        (FIXTURE.replace("33\t32\tconnected\tHDMI-A-1", "33\t32\tdisconnected\tHDMI-A-1"), "HDMI-A-2"),
    ],
)
def test_auto_discovery_selects_the_only_connected_hdmi(text, expected):
    resolved, provenance = resolve_display_config(
        parse_modetest_connectors(text), _auto_display()
    )
    assert resolved.stimulus_connector == expected
    assert provenance["connector_selection"] == "single_connected_hdmi"
    assert resolved.width_px == 1024 and resolved.height_px == 600
    assert resolved.refresh_hz == 59.82


def test_auto_discovery_requires_a_connected_hdmi_and_rejects_ambiguity():
    no_display = FIXTURE.replace("connected\tHDMI-A-1", "disconnected\tHDMI-A-1")
    no_display = no_display.replace("connected\tHDMI-A-2", "disconnected\tHDMI-A-2")
    with pytest.raises(DisplaySelectionError, match="no connected HDMI"):
        select_display(parse_modetest_connectors(no_display), _auto_display())
    with pytest.raises(DisplaySelectionError, match="Multiple displays detected"):
        select_display(parse_modetest_connectors(FIXTURE), _auto_display())


def test_explicit_connector_resolves_when_multiple_displays_are_connected():
    config = _auto_display(stimulus_connector="HDMI-A-2")
    selected = select_display(parse_modetest_connectors(FIXTURE), config)
    assert selected.connector.name == "HDMI-A-2"
    assert selected.mode.preferred


def test_configured_resolution_and_auto_mode_selection_support_different_screens():
    inventory = parse_modetest_connectors(FIXTURE)
    configured = replace(
        _auto_display(stimulus_connector="HDMI-A-1"),
        mode_selection_policy="configured",
        width_px=1280,
        height_px=720,
        refresh_hz=60.0,
    )
    selected = select_display(inventory, configured)
    assert (selected.mode.width_px, selected.mode.height_px, selected.mode.refresh_hz) == (
        1280, 720, 60.0
    )


@pytest.mark.parametrize(
    ("refresh_hz", "expected"),
    [(30, 15), (59.82, 30), (59.94, 30), (60, 30), (75, 38), (120, 60), (144, 72)],
)
def test_duration_quantization_uses_resolved_refresh_and_half_up(refresh_hz, expected):
    assert milliseconds_to_frames(500, refresh_hz) == expected


def test_duration_quantization_uses_one_frame_for_small_nonzero_requests():
    assert milliseconds_to_frames(0, 30) == 0
    assert milliseconds_to_frames(0.001, 30) == 1
    with pytest.raises(ValueError, match="finite"):
        milliseconds_to_frames(math.inf, 60)


def test_legacy_exact_frame_conversion_and_seeded_plan_remain_unchanged():
    assert seconds_to_frames(0.5, 60) == 30
    with pytest.raises(ValueError, match="not an integer"):
        seconds_to_frames(0.5, 59.82)
    plan = build_plan(NaturalImageSettings(
        images=("a.png", "b.png", "c.png"),
        seed=7,
        image_count=2,
        image_duration_s=0.5,
        refresh_hz=60,
        iti_frames=(42, 60),
        initial_gray_frames=180,
        final_gray_frames=180,
    ))
    assert [event.frame_count for event in plan.events if event.kind == "image"] == [30, 30]
    assert [event.frame_count for event in plan.events if event.event_id == "initial-gray"] == [180]
    assert "duration_provenance" not in plan.metadata


def test_portable_plan_quantizes_image_gray_and_seeded_itis_deterministically():
    settings = NaturalImageSettings(
        images=("a.png", "b.png", "c.png", "d.png"),
        seed=17,
        image_count=3,
        selection_seed=777,
        refresh_hz=59.94,
        image_duration_ms=500,
        initial_gray_duration_ms=250,
        final_gray_duration_ms=500,
        iti_duration_ms=(700, 1000),
        compatibility_profile="portable_display_only",
    )
    first = build_plan(settings)
    second = build_plan(settings)
    assert first.stable_json() == second.stable_json()
    assert [event.frame_count for event in first.events if event.kind == "image"] == [30] * 3
    assert next(event.frame_count for event in first.events if event.event_id == "initial-gray") == 15
    assert next(event.frame_count for event in first.events if event.event_id == "final-gray") == 30
    assert all(42 <= event.frame_count <= 60 for event in first.events if event.kind == "iti")
    durations = first.metadata["duration_provenance"]
    assert durations["image"]["requested_ms"] == 500
    assert durations["image"]["resolved_frames"] == 30
    assert durations["final_planned_total_frame_count"] == first.total_frames
    assert len(durations["iti"]) == 3


def test_portable_profile_accepts_seconds_and_rejects_legacy_frame_fields(tmp_path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (8, 4), (50, 80, 120)).save(asset_root / "image.png")
    config = replace(
        Config(),
        paths=replace(Config().paths, asset_root=asset_root),
        display=replace(Config().display, refresh_hz=75.0),
        protocol=replace(Config().protocol, parameters={
            "compatibility_profile": "portable_display_only",
            "image_duration_s": 0.5,
            "initial_gray_duration_s": 0.25,
            "final_gray_duration_s": 0.5,
            "iti_duration_s": [0.7, 1.0],
            "image_count": 1,
        }),
    )
    plan = build_demo_plan(config, seed=0, image_count=1)
    assert next(event.frame_count for event in plan.events if event.kind == "image") == 38
    assert next(event.frame_count for event in plan.events if event.event_id == "initial-gray") == 19
    legacy_fields = config.protocol.parameters | {"initial_gray_frames": 30}
    config = replace(config, protocol=replace(config.protocol, parameters=legacy_fields))
    with pytest.raises(ValueError, match="remove legacy frame setting"):
        build_demo_plan(config, seed=0, image_count=1)


def test_portable_profile_configuration_is_display_only_and_local_storage():
    config = load_config(PORTABLE_CONFIG)
    config.validate()
    assert config.display.backend == "kms"
    assert config.display.selection_policy == "auto_single"
    assert config.display.mode_selection_policy == "preferred"
    assert config.display.preview_connector is None
    assert config.display.physical_width_cm == config.display.physical_height_cm == 0
    assert config.display.eye_distance_cm == 0
    assert config.hardware.backend == "simulated"
    assert all(getattr(config.hardware, field) == -1 for field in (
        "reward_pin_bcm", "reward_right_pin_bcm", "reward_center_pin_bcm",
        "reward_4_pin_bcm", "airpuff_pin_bcm", "suction_pin_bcm",
        "lick_pin_bcm", "lick_right_pin_bcm", "lick_center_pin_bcm",
    ))
    assert config.cameras.devices == ()
    assert config.cameras.enabled_by_default is False
    assert config.paths.output_root == Path("/home/pi/rpi_vstim_test_data")
    assert "/mnt/behavbox_ssd" not in str(config.paths.output_root)
    assert config.protocol.parameters["compatibility_profile"] == "portable_display_only"
    assert config.protocol.parameters["image_count"] == 5


def test_mock_discovery_resolves_mode_before_the_portable_scientific_plan(tmp_path, monkeypatch):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (8, 4), (50, 80, 120)).save(asset_root / "image.png")
    config = load_config(PORTABLE_CONFIG)
    config = replace(
        config,
        paths=replace(config.paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
    )
    inventory = DisplayInventory((ConnectorInfo(
        "HDMI-A-1", "connected",
        (DisplayMode("1366x768", 1366, 768, 75.0, preferred=True),),
    ),))
    monkeypatch.setattr(
        "rpi_vstim.core.natural_image_demo.discover_modetest", lambda: inventory
    )
    prepared = prepare_natural_image_demo(config, session_id="resolved", image_count=1)
    image = next(event for event in prepared.plan.events if event.kind == "image")
    assert prepared.config.display.stimulus_connector == "HDMI-A-1"
    assert (prepared.config.display.width_px, prepared.config.display.height_px) == (1366, 768)
    assert prepared.config.display.refresh_hz == 75.0
    assert image.frame_count == 38
    assert prepared.display_provenance["selection_policy"] == "auto_single"
    assert prepared.display_provenance["selection_source"] == "auto"
    assert prepared.display_provenance["selected_drm_mode"] == "1366x768@75"
    assert prepared.plan.metadata["duration_provenance"]["final_planned_total_frame_count"] == prepared.plan.total_frames


def _portable_config_with_assets(tmp_path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (8, 4), (50, 80, 120)).save(asset_root / "image.png")
    config = load_config(PORTABLE_CONFIG)
    return replace(
        config,
        paths=replace(config.paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
    )


def _two_mode_inventory():
    return DisplayInventory((
        ConnectorInfo(
            "HDMI-A-1", "connected",
            (DisplayMode("1920x1080", 1920, 1080, 60.0, preferred=True),),
        ),
        ConnectorInfo(
            "HDMI-A-2", "connected",
            (DisplayMode("1024x600", 1024, 600, 59.82, preferred=True),),
        ),
    ))


def test_configured_connector_and_cli_override_precedence_and_provenance(tmp_path):
    config = _portable_config_with_assets(tmp_path)
    config = replace(
        config,
        display=replace(config.display, stimulus_connector="HDMI-A-1"),
    )
    configured = prepare_natural_image_demo(
        config,
        session_id="configured",
        image_count=1,
        discover_displays=_two_mode_inventory,
    )
    assert configured.config.display.stimulus_connector == "HDMI-A-1"
    assert configured.config.display.width_px == 1920
    assert configured.display_provenance["selection_source"] == "config"

    original_toml = PORTABLE_CONFIG.read_bytes()
    overridden = prepare_natural_image_demo(
        config,
        session_id="cli-override",
        image_count=1,
        stimulus_connector="HDMI-A-2",
        discover_displays=_two_mode_inventory,
    )
    assert overridden.config.display.stimulus_connector == "HDMI-A-2"
    assert overridden.config.display.width_px == 1024
    assert overridden.config.display.refresh_hz == 59.82
    assert overridden.display_provenance["selection_source"] == "cli"
    assert overridden.display_provenance["connector"] == "HDMI-A-2"
    assert PORTABLE_CONFIG.read_bytes() == original_toml


@pytest.mark.parametrize(
    ("connector", "inventory_factory", "message"),
    [
        ("HDMI-A-3", _two_mode_inventory, "configured connector is missing"),
        (
            "HDMI-A-2",
            lambda: DisplayInventory((
                ConnectorInfo("HDMI-A-2", "disconnected", ()),
            )),
            "not connected",
        ),
    ],
)
def test_cli_connector_override_requires_connected_display(
    tmp_path, connector, inventory_factory, message
):
    config = _portable_config_with_assets(tmp_path)
    with pytest.raises(NaturalImageDemoError, match=message):
        prepare_natural_image_demo(
            config,
            session_id="invalid-connector",
            image_count=1,
            stimulus_connector=connector,
            discover_displays=inventory_factory,
        )
    assert not config.paths.output_root.exists()


def test_no_display_error_is_actionable_before_plan_or_output_creation(tmp_path):
    config = _portable_config_with_assets(tmp_path)
    with pytest.raises(NaturalImageDemoError, match="no connected HDMI display"):
        prepare_natural_image_demo(
            config,
            session_id="no-display",
            image_count=1,
            discover_displays=lambda: DisplayInventory(()),
        )
    assert not config.paths.output_root.exists()


def test_interactive_menu_uses_discovered_modes_and_selected_connector(capsys):
    config = _auto_display()
    selected = cli._prompt_stimulus_connector(
        parse_modetest_connectors(FIXTURE), config, input_func=lambda _prompt: "2"
    )
    assert selected == "HDMI-A-2"
    output = capsys.readouterr().out
    assert "Multiple HDMI displays detected:" in output
    assert "HDMI-A-1  1024x600 @ 59.82 Hz (preferred)" in output
    assert "HDMI-A-2  1024x600 @ 59.82 Hz (preferred)" in output


def test_interactive_menu_retries_invalid_input_and_cancels_cleanly(capsys):
    values = iter(("nope", "9", "1"))
    selected = cli._prompt_stimulus_connector(
        parse_modetest_connectors(FIXTURE),
        _auto_display(),
        input_func=lambda _prompt: next(values),
    )
    assert selected == "HDMI-A-1"
    assert capsys.readouterr().out.count("Invalid selection") == 2
    with pytest.raises(cli.InteractiveDisplaySelectionCancelled):
        cli._prompt_stimulus_connector(
            parse_modetest_connectors(FIXTURE),
            _auto_display(),
            input_func=lambda _prompt: "q",
        )
    with pytest.raises(DisplaySelectionError, match="after 3 attempts"):
        cli._prompt_stimulus_connector(
            parse_modetest_connectors(FIXTURE),
            _auto_display(),
            input_func=lambda _prompt: "0",
        )


def test_interactive_menu_is_limited_to_terminal_manual_runs(monkeypatch):
    class Terminal:
        def __init__(self, interactive):
            self.interactive = interactive

        def isatty(self):
            return self.interactive

    monkeypatch.setattr(sys, "stdin", Terminal(True))
    monkeypatch.setattr(sys, "stdout", Terminal(True))
    for name in ("CI", "INVOCATION_ID", "NOTIFY_SOCKET"):
        monkeypatch.delenv(name, raising=False)
    config = load_config(PORTABLE_CONFIG)

    def args(*options):
        return cli.build_parser().parse_args([
            "natural-images", "run", "--mouse-id", "screen-test", *options,
        ])

    assert cli._interactive_display_enabled(args(), config)
    assert not cli._interactive_display_enabled(args("--json"), config)
    assert not cli._interactive_display_enabled(args("--operator-control"), config)
    assert not cli._interactive_display_enabled(
        args("--operator-session-metadata", "launch.json"), config
    )
    assert not cli._interactive_display_enabled(
        args("--stimulus-connector", "HDMI-A-2"), config
    )
    configured = replace(config, display=replace(config.display, stimulus_connector="HDMI-A-1"))
    assert not cli._interactive_display_enabled(args(), configured)
    monkeypatch.setenv("CI", "1")
    assert not cli._interactive_display_enabled(args(), config)
    monkeypatch.delenv("CI")
    monkeypatch.setenv("INVOCATION_ID", "systemd-test")
    assert not cli._interactive_display_enabled(args(), config)
    monkeypatch.delenv("INVOCATION_ID")
    monkeypatch.setattr(sys, "stdin", Terminal(False))
    assert not cli._interactive_display_enabled(args(), config)
    monkeypatch.setattr(sys, "stdin", Terminal(True))
    monkeypatch.setattr(sys, "stdout", Terminal(False))
    assert not cli._interactive_display_enabled(args(), config)


def test_cancelled_cli_selection_creates_no_session_or_hardware(tmp_path, monkeypatch, capsys):
    config = _portable_config_with_assets(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "_interactive_display_enabled", lambda _args, _config: True)
    monkeypatch.setattr(cli, "discover_modetest", lambda: _two_mode_inventory())
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    monkeypatch.setattr(
        cli,
        "prepare_natural_image_demo",
        lambda *_args, **_kwargs: pytest.fail("cancel must not prepare a session"),
    )
    assert cli.main([
        "natural-images", "run", "--mouse-id", "screen-test", "--config", "unused.toml",
    ]) == 0
    assert "no session was created" in capsys.readouterr().out
    assert not config.paths.output_root.exists()


def test_cli_connector_override_reaches_plan_and_renderer_config_without_toml_write(
    tmp_path, monkeypatch, capsys
):
    config = _portable_config_with_assets(tmp_path)
    original_toml = PORTABLE_CONFIG.read_bytes()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "_interactive_display_enabled", lambda _args, _config: False)
    monkeypatch.setattr(
        "rpi_vstim.core.natural_image_demo.discover_modetest", _two_mode_inventory
    )
    observed = {}

    def fake_run(resolved_config, **kwargs):
        observed["config"] = resolved_config
        observed["prepared"] = kwargs["prepared"]
        return SimpleNamespace(
            session_root=resolved_config.paths.output_root / "unused-session",
            status="COMPLETE",
            error=None,
            ok=True,
            raw_lick_count={},
            classified_lick_count={},
            camera_manifest=[],
            event_diagnostics={},
            camera_preview={},
            audio_summary={},
        )

    monkeypatch.setattr(cli, "run_natural_image_demo", fake_run)
    assert cli.main([
        "natural-images", "run", "--mouse-id", "screen-test", "--config", str(PORTABLE_CONFIG),
        "--stimulus-connector", "HDMI-A-2", "--output-root", "~/rpi_vstim_test_data",
        "--image-count", "1", "--json",
    ]) == 0
    prepared = observed["prepared"]
    assert observed["config"].display is prepared.config.display
    assert prepared.config.display.stimulus_connector == "HDMI-A-2"
    assert prepared.config.display.width_px == 1024
    assert prepared.display_provenance["selection_source"] == "cli"
    assert prepared.config.paths.output_root == home / "rpi_vstim_test_data"
    assert PORTABLE_CONFIG.read_bytes() == original_toml


def test_interactive_cli_selection_is_frozen_and_recorded(tmp_path, monkeypatch, capsys):
    config = _portable_config_with_assets(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "_interactive_display_enabled", lambda _args, _config: True)
    monkeypatch.setattr(cli, "discover_modetest", _two_mode_inventory)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    observed = {}

    def fake_run(resolved_config, **kwargs):
        observed["config"] = resolved_config
        observed["prepared"] = kwargs["prepared"]
        return SimpleNamespace(
            session_root=resolved_config.paths.output_root / "unused-session",
            status="COMPLETE",
            error=None,
            ok=True,
            raw_lick_count={},
            classified_lick_count={},
            camera_manifest=[],
            event_diagnostics={},
            camera_preview={},
            audio_summary={},
        )

    monkeypatch.setattr(cli, "run_natural_image_demo", fake_run)
    assert cli.main([
        "natural-images", "run", "--mouse-id", "screen-test", "--config", str(PORTABLE_CONFIG),
        "--image-count", "1",
    ]) == 0
    prepared = observed["prepared"]
    assert prepared.config.display.stimulus_connector == "HDMI-A-2"
    assert prepared.config.display.width_px == 1024
    assert prepared.display_provenance["selection_source"] == "interactive"
    assert observed["config"].display is prepared.config.display
    output = capsys.readouterr().out
    assert "HDMI-A-2 1920x1080" not in output
    assert "HDMI-A-2 1024x600" in output


def test_display_inventory_reports_configured_selection_from_discovery(monkeypatch):
    monkeypatch.setattr(
        "rpi_vstim.display.diagnostics.discover_modetest",
        lambda **_kwargs: _two_mode_inventory(),
    )
    result = display_inventory(_auto_display(stimulus_connector="HDMI-A-1"))
    assert result["configured_selection"]["connector"] == "HDMI-A-1"
    assert result["configured_selection"]["selection_source"] == "config"
    assert result["configured_selection"]["width_px"] == 1920


def test_original_rig_keeps_hdmi_a2_and_legacy_profile():
    config = load_config("config/rigs/pi5_natural_image_demo.example.toml")
    assert config.display.stimulus_connector == "HDMI-A-2"
    assert config.protocol.parameters["compatibility_profile"] == "natural_legacy_plain"
    assert not cli._interactive_display_enabled(
        SimpleNamespace(
            stimulus_connector=None,
            as_json=False,
            operator_control=False,
            operator_session_metadata=None,
        ),
        config,
    )


def test_portable_settings_run_through_hardware_free_fake_display(tmp_path, monkeypatch):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (8, 4), (50, 80, 120)).save(asset_root / "image.png")
    config = load_config(PORTABLE_CONFIG)
    parameters = dict(config.protocol.parameters)
    parameters.update(
        image_count=1,
        image_duration_ms=1,
        initial_gray_duration_ms=1,
        final_gray_duration_ms=1,
        iti_duration_ms=[1],
    )
    config = replace(
        config,
        paths=replace(config.paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
        protocol=replace(config.protocol, parameters=parameters),
    )
    monkeypatch.setattr(
        "rpi_vstim.core.natural_image_demo.discover_modetest",
        lambda: (_ for _ in ()).throw(AssertionError("simulation must not discover or acquire KMS")),
    )
    prepared = prepare_natural_image_demo(
        config, session_id="portable-fake", image_count=1, simulate=True
    )
    result = run_natural_image_demo(
        config,
        mouse_id="screen-test",
        session_id="portable-fake",
        image_count=1,
        prepared=prepared,
        simulate=True,
    )
    assert result.ok
    timing = json.loads((result.session_root / "timing_provenance.json").read_text())
    assert timing["native_presentation"]["physical_kms"] is False
    assert timing["durations"]["image"]["resolved_frames"] == 1
    final = json.loads((result.session_root / "final_status.json").read_text())
    assert final["natural_image_demo"]["display_backend"] == "simulated"


def test_display_list_cli_is_read_only_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "display_inventory", lambda config=None: {
        "connectors": [{
            "connector": "HDMI-A-1",
            "status": "connected",
            "modes": [{
                "mode": "1280x720", "width_px": 1280, "height_px": 720,
                "refresh_hz": 75.0, "preferred": True,
            }],
        }],
        "configured_selection": None,
    })
    assert cli.main(["hardware", "display-list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["connectors"][0]["modes"][0]["refresh_hz"] == 75.0


def test_display_list_human_output_includes_modes_and_configured_selection(monkeypatch, capsys):
    monkeypatch.setattr(cli, "display_inventory", lambda config=None: {
        "connectors": [{
            "connector": "HDMI-A-2", "status": "connected",
            "modes": [{
                "mode": "1024x600", "width_px": 1024, "height_px": 600,
                "refresh_hz": 59.82, "preferred": True,
            }],
        }],
        "configured_selection": {
            "connector": "HDMI-A-2", "width_px": 1024, "height_px": 600,
            "refresh_hz": 59.82, "selection_source": "config",
        },
    })
    assert cli.main(["hardware", "display-list"]) == 0
    output = capsys.readouterr().out
    assert "HDMI-A-2 (connected)" in output
    assert "1024x600 @ 59.82 Hz (preferred)" in output
    assert "Configured stimulus: HDMI-A-2" in output
