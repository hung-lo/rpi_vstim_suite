import pytest

from rpi_vstim.core.config import DisplayConfig
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.display.frame_program import FrameProgram
from rpi_vstim.hardware.simulated import SimulatedHardwareBackend


def test_fake_display_is_deterministic_and_safe():
    display = FakeDisplayBackend()
    display.open(DisplayConfig())
    result = display.present(FrameProgram(1280, 720, 60.0, "RGB565", 3), sequence_id="demo")
    assert result.completed_frame_count == 3
    assert display.presented == [("demo", 3)]
    display.close()


def test_fake_display_rejects_refresh_mismatch():
    display = FakeDisplayBackend()
    display.open(DisplayConfig(refresh_hz=60.0))
    with pytest.raises(ValueError, match="refresh_hz"):
        display.present(FrameProgram(1280, 720, 59.0, "RGB565", 3), sequence_id="wrong-rate")


def test_simulated_hardware_starts_safe():
    hardware = SimulatedHardwareBackend()
    assert hardware.start().outputs_safe
    hardware.stop()
    assert hardware.outputs_safe
