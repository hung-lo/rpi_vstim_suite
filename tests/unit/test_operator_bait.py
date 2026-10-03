from dataclasses import replace

import pytest

from rpi_vstim.core.config import Config, ConfigError, config_from_mapping
from rpi_vstim.hardware.operator_bait import (
    LgpioOperatorBaitMonitor,
    ManualBaitRequest,
    ManualBaitService,
    OperatorBaitStateMachine,
)


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

    def __init__(self):
        self.calls = []
        self.levels = {23: 0}
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


class FakeRewardController:
    def __init__(self):
        self.calls = []

    def deliver(self, **kwargs):
        self.calls.append(kwargs)
        return "delivery"


def enabled_config():
    return config_from_mapping(
        {
            "operator_controls": {
                "bait_button_enabled": True,
                "bait_button_gpio": 23,
                "bait_button_idle_level": 0,
                "bait_button_active_level": 1,
                "bait_reward_ul": 3.0,
                "minimum_interval_ms": 1000,
                "bait_button_release_stable_ms": 25,
            }
        }
    )


def test_button_state_machine_emits_one_request_per_rearmed_contact():
    state = OperatorBaitStateMachine(
        idle_level=0,
        active_level=1,
        release_stable_ms=25,
        min_interval_ms=1000,
        initial_timestamp_ns=0,
    )

    assert state.process_edge(1, 1_000_000_000).request_index == 1
    assert state.process_edge(1, 1_001_000_000) is None
    state.process_edge(0, 1_010_000_000)
    assert state.process_edge(1, 1_020_000_000) is None
    state.process_edge(0, 1_030_000_000)
    assert state.process_edge(1, 1_070_000_000) is None  # lockout still active
    state.process_edge(0, 1_071_000_000)
    request = state.process_edge(1, 2_100_000_000)
    assert request is not None and request.request_index == 2


def test_monitor_claims_only_gpio23_and_releases_cleanly():
    api = FakeLgpio()
    requests = []
    raw_edges = []
    monitor = LgpioOperatorBaitMonitor(
        enabled_config(),
        api=api,
        on_raw_edge=raw_edges.append,
        on_request=requests.append,
        clock_ns=lambda: 1_000_000_000,
    )
    monitor.start()
    callback = api.callbacks[0]
    callback.emit(1, 1_000_000_000)
    callback.emit(1, 1_001_000_000)
    callback.emit(0, 1_010_000_000)
    callback.emit(1, 1_020_000_000)
    callback.emit(0, 1_030_000_000)
    callback.emit(1, 1_070_000_000)
    monitor.stop()

    assert len(requests) == 1
    assert requests[0].bcm_pin == 23
    assert len(raw_edges) == 6
    assert monitor.last_level == 1
    assert ("claim_alert", 9, 23, 2, 0) in api.calls
    assert ("free", 9, 23) in api.calls
    gpio_calls = [
        call
        for call in api.calls
        if call[0] in {"claim_alert", "read", "callback", "free"}
    ]
    assert all(call[2] == 23 for call in gpio_calls)
    assert api.callbacks[0].cancelled


def test_manual_bait_service_calls_the_existing_reward_controller_once():
    reward = FakeRewardController()
    events = []
    service = ManualBaitService(reward, session_id="session-1", event_sink=events.append)

    result = service.handle_request(ManualBaitRequest(23, 123, 4))

    assert result == "delivery"
    assert reward.calls == [
        {"command_id": "manual-bait-4", "session_id": "session-1"}
    ]
    assert events == [
        {
            "event": "manual_bait_request",
            "role": "operator_bait_button",
            "gpio_bcm": 23,
            "monotonic_ns": 123,
            "request_index": 4,
            "session_id": "session-1",
        }
    ]


def test_manual_bait_service_rejects_non_button_requests():
    service = ManualBaitService(FakeRewardController())
    with pytest.raises(RuntimeError, match="canonical BCM GPIO23"):
        service.handle_request(ManualBaitRequest(15, 123, 1))


def test_operator_configuration_requires_explicit_polarity_when_enabled():
    with pytest.raises(ConfigError, match="explicit idle and active"):
        config_from_mapping({"operator_controls": {"bait_button_enabled": True, "bait_reward_ul": 3.0}})


def test_canonical_pin_policy_and_irig_reservation_are_enforced():
    config = enabled_config()
    assert config.hardware.lick_center_pin_bcm == 15
    assert config.operator_controls.bait_button_gpio == 23
    with pytest.raises(ConfigError, match="GPIO9.*reserved exclusively"):
        config_from_mapping({"hardware": {"ttl_pin_bcm": 9}})
    with pytest.raises(ConfigError, match="reserved"):
        config_from_mapping({"hardware": {"reward_pin_bcm": 9}})
    with pytest.raises(ConfigError, match="canonical BCM GPIO23"):
        config_from_mapping({"operator_controls": {"bait_button_gpio": 15}})


def test_disabled_button_does_not_assume_polarity():
    config = replace(Config(), operator_controls=Config().operator_controls)
    assert config.operator_controls.bait_button_enabled is False
    assert config.operator_controls.bait_button_idle_level is None


def test_manual_interval_name_is_supported_as_a_config_alias():
    config = config_from_mapping(
        {"operator_controls": {"manual_bait_min_interval_ms": 1200}}
    )
    assert config.operator_controls.minimum_interval_ms == 1200
