import pytest

from rpi_vstim.core.config import DisplayConfig
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.display.frame_program import FrameProgram
from rpi_vstim.display.kms import KmsDisplayBackend
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


def test_kms_open_uses_selected_probe_and_presents_native_result(monkeypatch):
    monkeypatch.setattr(
        "rpi_vstim.display.kms.probe_config",
        lambda config: {
            "stimulus": {
                "connector": "HDMI-A-1",
                "mode": "1024x600",
                "refresh_hz": 59.82,
            },
            "preview": {"connector": "HDMI-A-2"},
        },
    )
    monkeypatch.setattr(
        "rpi_vstim.display.kms.run_native_probe",
        lambda config, **kwargs: {
            "connector": "HDMI-A-1",
            "selected_mode": "1024x600@59.82",
            "pixel_format": "RGB565",
            "requested_frame_count": kwargs["frames"],
            "completed_frame_count": kwargs["frames"],
            "first_page_flip_monotonic_ns": 100,
            "last_page_flip_monotonic_ns": 100_000,
            "first_page_flip_realtime_ns": 200,
            "mean_vblank_interval_us": 16_683.0,
            "std_vblank_interval_us": 2.0,
            "maximum_vblank_interval_us": 16_700.0,
            "missed_vblank_count": 0,
            "aborted": False,
        },
    )
    display = KmsDisplayBackend()
    info = display.open(DisplayConfig(width_px=1024, height_px=600, refresh_hz=59.82))
    assert info.connector == "HDMI-A-1"
    result = display.present_color((255, 255, 255), frames=2)
    assert result.completed_frame_count == 2
    assert result.missed_vblank_count == 0
    display.close()


def test_kms_open_failure_does_not_leave_partial_state(monkeypatch):
    def fail(_config):
        raise RuntimeError("connector unavailable")

    monkeypatch.setattr("rpi_vstim.display.kms.probe_config", fail)
    display = KmsDisplayBackend()
    with pytest.raises(RuntimeError, match="connector"):
        display.open(DisplayConfig())
    assert display.config is None
    assert display.info is None


def test_kms_present_failure_closes_backend(monkeypatch):
    monkeypatch.setattr(
        "rpi_vstim.display.kms.probe_config",
        lambda config: {
            "stimulus": {
                "connector": "HDMI-A-1",
                "mode": "1024x600",
                "refresh_hz": 59.82,
            },
            "preview": None,
        },
    )
    monkeypatch.setattr(
        "rpi_vstim.display.kms.run_native_probe",
        lambda config, **kwargs: (_ for _ in ()).throw(RuntimeError("page-flip timeout")),
    )
    display = KmsDisplayBackend()
    display.open(DisplayConfig(width_px=1024, height_px=600, refresh_hz=59.82))
    with pytest.raises(RuntimeError, match="page-flip"):
        display.present_color((0, 0, 0), frames=1)
    assert display.config is None
    assert display.info is None
