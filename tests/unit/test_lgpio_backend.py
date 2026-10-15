from dataclasses import replace

import pytest

from rpi_vstim.core.config import HardwareConfig
from rpi_vstim.hardware.lgpio_backend import LgpioBackend, LgpioBackendError


class FakeLgpio:
    def __init__(self):
        self.calls = []
        self.levels = {}

    def gpiochip_open(self, chip):
        self.calls.append(("open", chip))
        return 7

    def gpio_claim_output(self, handle, flags, pin, level):
        self.calls.append(("claim", handle, flags, pin, level))
        self.levels[pin] = level
        return 0

    def gpio_write(self, handle, pin, level):
        self.calls.append(("write", handle, pin, level))
        self.levels[pin] = level
        return 0

    def gpio_read(self, handle, pin):
        self.calls.append(("read", handle, pin))
        return self.levels[pin]

    def gpio_free(self, handle, pin):
        self.calls.append(("free", handle, pin))
        return 0

    def gpiochip_close(self, handle):
        self.calls.append(("close", handle))
        return 0


class FakeClock:
    def __init__(self):
        self.now = 0

    def ns(self):
        self.now += 1_000
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1_000_000_000)


def test_reward_session_claims_and_controls_only_configured_gpio19():
    api = FakeLgpio()
    config = HardwareConfig()
    backend = LgpioBackend(config, roles=("reward",), api=api)
    backend.start()
    backend.set_level("reward", 1)
    backend.stop()

    assert [call[3] for call in api.calls if call[0] == "claim"] == [19]
    assert [call[2] for call in api.calls if call[0] == "write"] == [19, 19]
    assert not any(25 in call for call in api.calls if call[0] in {"claim", "write", "read", "free"})


def test_vacuum_role_resolves_configured_gpio25_and_not_reward():
    api = FakeLgpio()
    backend = LgpioBackend(HardwareConfig(), roles=("vacuum",), api=api)
    backend.start()
    backend.set_level("vacuum", 1)
    backend.stop()

    assert [call[3] for call in api.calls if call[0] == "claim"] == [25]
    assert not any(19 in call for call in api.calls if call[0] in {"claim", "write", "read", "free"})


def test_initial_levels_are_explicit_and_active_polarity_is_unresolved():
    config = replace(HardwareConfig(), reward_initial_level=1, suction_initial_level=0)
    assert config.output_line("reward").initial_level == 1
    assert config.output_line("vacuum").initial_level == 0
    assert config.output_line("reward").active_level is None
    assert config.output_line("vacuum").active_level is None


def test_pulse_returns_to_requested_baseline_and_records_timestamps():
    api = FakeLgpio()
    clock = FakeClock()
    backend = LgpioBackend(HardwareConfig(), roles=("reward",), api=api, clock_ns=clock.ns, sleep=clock.sleep)
    backend.start()
    pulse = backend.pulse("reward", 1, 0.05, baseline_level=0)
    backend.stop()

    assert pulse.target.requested_level == 1
    assert pulse.baseline.requested_level == 0
    assert pulse.actual_duration_s == pytest.approx(0.05, abs=0.00001)
    assert pulse.target.completed_monotonic_ns < pulse.baseline.completed_monotonic_ns


def test_start_failure_releases_already_claimed_lines_and_chip():
    api = FakeLgpio()
    original = api.gpio_claim_output

    def fail_on_second(handle, flags, pin, level):
        if pin == 25:
            raise RuntimeError("busy")
        return original(handle, flags, pin, level)

    api.gpio_claim_output = fail_on_second
    with pytest.raises(RuntimeError, match="busy"):
        LgpioBackend(HardwareConfig(), api=api).start()

    assert ("free", 7, 19) in api.calls
    assert ("close", 7) in api.calls


def test_context_cleanup_runs_for_keyboard_interrupt():
    api = FakeLgpio()
    backend = LgpioBackend(HardwareConfig(), roles=("reward",), api=api)
    with pytest.raises(KeyboardInterrupt), backend:
        raise KeyboardInterrupt

    assert not backend.started
    assert ("free", 7, 19) in api.calls
    assert ("close", 7) in api.calls


def test_reserved_gpio9_cannot_be_claimed_by_normal_output_backend():
    api = FakeLgpio()
    config = replace(HardwareConfig(), reward_pin_bcm=9)
    backend = LgpioBackend(config, roles=("reward",), api=api)

    with pytest.raises(LgpioBackendError, match="GPIO9.*IRIG"):
        backend.start()

    assert not any(call[0] == "claim" for call in api.calls)
    assert ("close", 7) in api.calls


def test_irig_role_is_not_a_normal_output_role():
    with pytest.raises(ValueError, match="only reward and vacuum"):
        LgpioBackend(HardwareConfig(), roles=("irig_output",))


def test_sound_trigger_gpio24_is_not_acquired_by_reward_backend():
    api = FakeLgpio()
    config = replace(HardwareConfig(), reward_pin_bcm=24)
    backend = LgpioBackend(config, roles=("reward",), api=api)
    with pytest.raises(LgpioBackendError, match="GPIO24.*sound_trigger_2"):
        backend.start()
    assert not any(call[0] == "claim" for call in api.calls)


def test_sound_trigger_gpio23_is_not_acquired_by_reward_backend():
    api = FakeLgpio()
    config = replace(HardwareConfig(), reward_pin_bcm=23)
    backend = LgpioBackend(config, roles=("reward",), api=api)
    with pytest.raises(LgpioBackendError, match="GPIO23.*sound_trigger_1"):
        backend.start()
    assert not any(call[0] == "claim" for call in api.calls)
