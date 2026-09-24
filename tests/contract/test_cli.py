from rpi_vstim.cli import main


def test_list_protocols(capsys):
    assert main(["list-protocols"]) == 0
    assert "natural-images" in capsys.readouterr().out


def test_doctor_is_non_hardware(capsys):
    assert main(["doctor", "--json"]) == 0
    assert '"hardware_access": false' in capsys.readouterr().out

