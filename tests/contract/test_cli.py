from rpi_vstim.cli import main
from rpi_vstim.core.config import config_from_mapping
from rpi_vstim.core.dry_run import build_dry_run_report


def test_list_protocols(capsys):
    assert main(["list-protocols"]) == 0
    assert "natural-images" in capsys.readouterr().out


def test_doctor_is_non_hardware(capsys):
    assert main(["doctor", "--json"]) == 0
    assert '"hardware_access": false' in capsys.readouterr().out


def test_telemetry_loopback_commands_are_local_only(capsys):
    assert main(["telemetry", "demo", "--messages", "2", "--json"]) == 0
    assert '"received": 2' in capsys.readouterr().out
    assert main(["telemetry", "benchmark", "--messages", "4"]) == 0
    assert '"messages": 4' in capsys.readouterr().out


def test_session_validate_alias_is_read_only(tmp_path, capsys):
    assert main(["session", "validate", str(tmp_path), "--json"]) == 0
    assert '"incomplete": true' in capsys.readouterr().out


def test_preflight_and_run_dry_run_are_non_hardware(capsys):
    assert main(["preflight", "--protocol", "natural-images", "--json"]) == 0
    assert '"hardware_access": false' in capsys.readouterr().out
    assert main(["run", "natural-images", "--dry-run"]) == 0
    assert "hardware_access=False" in capsys.readouterr().out


def test_preflight_text_includes_operator_budget_and_camera_fields(capsys):
    assert main(["preflight"]) == 0
    output = capsys.readouterr().out
    assert "asset_digest=" in output
    assert "ram_bytes=" in output
    assert "storage_bytes=" in output
    assert "cameras=none" in output


def test_reward_preflight_does_not_write_configured_root(tmp_path):
    config = config_from_mapping(
        {"paths": {"output_root": str(tmp_path)}, "protocol": {"name": "reward-conditioning"}}
    )
    report = build_dry_run_report(config, protocol_name="reward-conditioning")
    assert report["plan"]["event_count"] == 500
    assert not (tmp_path / ".simulation_reward_state").exists()


def test_every_software_groundwork_protocol_runs_without_hardware(tmp_path, capsys):
    protocols = (
        "natural-images",
        "reward-conditioning",
        "spout-training",
        "drifting-gratings",
        "retinotopy",
    )
    for protocol in protocols:
        assert main(
            [
                "run",
                protocol,
                "--simulate",
                "--output-root",
                str(tmp_path / protocol),
                "--session-id",
                "session",
            ]
        ) == 0
        assert "COMPLETE" in capsys.readouterr().out


def test_explicit_config_protocol_mismatch_is_rejected(tmp_path, capsys):
    config_path = tmp_path / "natural.toml"
    config_path.write_text('[protocol]\nname = "natural-images"\n', encoding="utf-8")
    assert main(
        [
            "run",
            "retinotopy",
            "--simulate",
            "--config",
            str(config_path),
            "--output-root",
            str(tmp_path / "mismatch"),
        ]
    ) == 2
    assert "protocol/config mismatch" in capsys.readouterr().err


def test_native_kms_probe_cli_is_explicit_and_json(monkeypatch, capsys):
    monkeypatch.setattr(
        "rpi_vstim.cli.run_native_probe",
        lambda config, **kwargs: {
            "connector": config.stimulus_connector,
            "modeset": False,
            "page_flip": False,
            "probe_only": kwargs["probe_only"],
        },
    )
    assert main(["hardware", "kms-probe", "--json"]) == 0
    assert '"modeset": false' in capsys.readouterr().out
