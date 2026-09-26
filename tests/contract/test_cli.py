from rpi_vstim.cli import main


def test_list_protocols(capsys):
    assert main(["list-protocols"]) == 0
    assert "natural-images" in capsys.readouterr().out


def test_doctor_is_non_hardware(capsys):
    assert main(["doctor", "--json"]) == 0
    assert '"hardware_access": false' in capsys.readouterr().out


def test_preflight_and_run_dry_run_are_non_hardware(capsys):
    assert main(["preflight", "--protocol", "natural-images", "--json"]) == 0
    assert '"hardware_access": false' in capsys.readouterr().out
    assert main(["run", "natural-images", "--dry-run"]) == 0
    assert "hardware_access=False" in capsys.readouterr().out


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
