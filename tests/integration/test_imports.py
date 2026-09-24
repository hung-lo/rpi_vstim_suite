def test_imports_are_safe_on_development_machine():
    import rpi_vstim
    from rpi_vstim.display.kms import KmsDisplayBackend
    from rpi_vstim.hardware.lgpio_backend import LgpioBackend

    assert rpi_vstim.__version__ == "0.1.0"
    assert KmsDisplayBackend.name == "kms"
    assert LgpioBackend

