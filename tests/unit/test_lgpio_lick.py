import pytest

from rpi_vstim.core.config import HardwareConfig
from rpi_vstim.hardware.lgpio_lick import LgpioLickError, LgpioLickMonitor, LickEventRecorder


class FakeCallback:
    def __init__(self, pin, callback):
        self.pin = pin
        self.callback = callback
        self.cancelled = False

    def emit(self, level, timestamp_ns):
        self.callback(0, self.pin, level, timestamp_ns)

    def cancel(self):
        self.cancelled = True


class FakeLgpio:
    BOTH_EDGES = 2

    def __init__(self, levels=None):
        self.calls = []
        self.levels = {26: 0, 27: 0, **(levels or {})}
        self.callbacks = []

    def gpiochip_open(self, chip):
        self.calls.append(("open", chip))
        return 9

    def gpio_claim_alert(self, handle, pin, edge, flags):
        self.calls.append(("claim_alert", handle, pin, edge, flags))
        return 0

    def gpio_read(self, handle, pin):
        self.calls.append(("read", handle, pin))
        return self.levels[pin]

    def callback(self, handle, pin, edge, callback):
        item = FakeCallback(pin, callback)
        self.callbacks.append(item)
        self.calls.append(("callback", handle, pin, edge))
        return item

    def gpio_free(self, handle, pin):
        self.calls.append(("free", handle, pin))
        return 0

    def gpiochip_close(self, handle):
        self.calls.append(("close", handle))
        return 0


def _emit_burst(callback, base_ns):
    for level, offset_ms in ((1, 30), (0, 35), (1, 40), (0, 45), (1, 50), (0, 100)):
        callback.emit(level, base_ns + offset_ms * 1_000_000)


def test_dual_monitor_preserves_raw_edges_and_classifies_each_channel_independently():
    api = FakeLgpio()
    recorder = LickEventRecorder()
    monitor = LgpioLickMonitor(
        HardwareConfig(),
        api=api,
        on_raw_edge=recorder.record_raw,
        on_classified=recorder.record_classified,
        clock_ns=lambda: 1_000_000_000,
    )
    monitor.start()
    for burst in range(20):
        _emit_burst(api.callbacks[0], 1_000_000_000 + burst * 200_000_000)
        _emit_burst(api.callbacks[1], 1_000_000_000 + burst * 200_000_000)
    monitor.stop()

    assert monitor.raw_edge_count == {"lick_left": 120, "lick_right": 120}
    assert monitor.classified_count == {"lick_left": 20, "lick_right": 20}
    assert [item.channel for item in recorder.classified_licks].count("lick_left") == 20
    assert [item.channel for item in recorder.classified_licks].count("lick_right") == 20
    assert len(recorder.raw_edges) == 240
    assert monitor.last_level == {"lick_left": 0, "lick_right": 0}
    assert not any(15 in call for call in api.calls)
    assert all(item.cancelled for item in api.callbacks)
    assert ("free", 9, 26) in api.calls
    assert ("free", 9, 27) in api.calls


def test_monitor_rejects_non_idle_start_and_releases_claims():
    api = FakeLgpio(levels={26: 1})
    monitor = LgpioLickMonitor(HardwareConfig(), api=api)
    with pytest.raises(LgpioLickError, match="expected idle"):
        monitor.start()

    assert not monitor.started
    assert ("free", 9, 26) in api.calls
    assert ("close", 9) in api.calls


def test_configured_timing_is_passed_to_each_channel():
    api = FakeLgpio()
    config = HardwareConfig(release_stable_ms=31, min_classified_lick_interval_ms=81)
    monitor = LgpioLickMonitor(config, api=api)
    monitor.start()
    _emit_burst(api.callbacks[0], 1_000_000_000)
    monitor.stop()

    assert monitor.classified_count["lick_left"] == 1
