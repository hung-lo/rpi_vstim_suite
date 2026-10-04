import errno
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from rpi_vstim.core.config import Config, HardwareConfig, config_from_mapping
from rpi_vstim.hardware.operator_bait import ManualBaitRequest, ManualBaitService
from rpi_vstim.hardware.operator_control import (
    LocalOperatorControlEndpoint,
    OperatorControlService,
    send_manual_bait,
)
from rpi_vstim.hardware.ownership import RewardHardwareBusyError, RewardHardwareOwnership
from rpi_vstim.hardware.reward import RewardDurationResolution
from rpi_vstim.hardware.water import WaterAccounting, WaterLimitError
from rpi_vstim.hardware.water_service import (
    MAX_CONTINUOUS_WATER_OPEN_SECONDS,
    WaterHoldStateMachine,
    WaterServiceController,
    WaterServiceError,
    validate_service_seconds,
)


class FakeBackend:
    def __init__(self):
        self.transitions = []

    def set_level(self, role, level):
        self.transitions.append((role, level))


class FakeRewardController:
    def __init__(self):
        self.resolution = RewardDurationResolution(10, 3.0, "cal", calibration_sha256="sha")
        self.calls = []

    def deliver(self, **kwargs):
        self.calls.append(kwargs)
        return "delivery"


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += round(seconds * 1_000_000_000)


def reward_config():
    return replace(
        Config(),
        hardware=HardwareConfig(reward_active_level=1),
    )


def test_water_prime_is_one_continuous_open_and_has_hard_limit():
    clock = FakeClock()
    backend = FakeBackend()
    events = []
    controller = WaterServiceController(
        backend,
        reward_config().hardware,
        clock_ns=clock,
        sleep=clock.sleep,
        event_sink=events.append,
    )

    delivery = controller.prime(0.05)

    assert backend.transitions == [("reward_left", 1), ("reward_left", 0)]
    assert delivery[0].event == "water_service_open"
    assert delivery[-1].event == "water_service_close"
    assert events == list(delivery)
    with pytest.raises(WaterServiceError, match="<= 300"):
        controller.prime(MAX_CONTINUOUS_WATER_OPEN_SECONDS + 1)
    assert backend.transitions == [("reward_left", 1), ("reward_left", 0)]


def test_water_prime_interrupt_closes_the_line():
    backend = FakeBackend()

    def interrupt(_seconds):
        raise KeyboardInterrupt

    controller = WaterServiceController(
        backend,
        reward_config().hardware,
        sleep=interrupt,
    )

    with pytest.raises(KeyboardInterrupt):
        controller.prime(1)
    assert backend.transitions == [("reward_left", 1), ("reward_left", 0)]


def test_water_service_hold_requires_release_and_times_out_without_reopen():
    clock = FakeClock()
    backend = FakeBackend()
    controller = WaterServiceController(
        backend,
        reward_config().hardware,
        clock_ns=clock,
        sleep=clock.sleep,
    )
    hold = WaterHoldStateMachine(
        controller,
        idle_level=0,
        active_level=1,
        release_stable_ms=25,
        clock_ns=clock,
    )

    hold.handle_level(1, 1_000_000)
    assert controller.open
    hold.check_timeout(now_ns=301_000_000_000)
    assert not controller.open
    hold.handle_level(1, 301_001_000_000)
    assert not controller.open
    hold.handle_level(0, 301_002_000_000)
    hold.handle_level(0, 301_030_000_000)
    hold.handle_level(1, 301_031_000_000)
    assert controller.open
    hold.handle_level(0, 301_032_000_000)
    assert not controller.open
    assert backend.transitions == [("reward_left", 1), ("reward_left", 0), ("reward_left", 1), ("reward_left", 0)]


def test_water_accounting_separates_task_and_manual_bait():
    accounting = WaterAccounting(max_manual_bait_water_ul=5)
    accounting.record_task_reward(2)
    accounting.reserve_manual_bait(3)
    assert accounting.as_dict() == {
        "task_reward_water_ul": 2,
        "operator_bait_water_ul": 3,
        "total_delivered_water_ul": 5,
        "max_manual_bait_water_ul": 5,
    }
    with pytest.raises(WaterLimitError):
        accounting.reserve_manual_bait(3)


def test_terminal_and_remote_bait_share_controller_and_respect_water_cap():
    controller = FakeRewardController()
    events = []
    service = ManualBaitService(
        controller,
        session_id="s",
        event_sink=events.append,
        water_accounting=WaterAccounting(max_manual_bait_water_ul=3),
    )

    service.handle_request(ManualBaitRequest(None, 1, 1, "terminal"))
    with pytest.raises(WaterLimitError):
        service.handle_request(ManualBaitRequest(None, 2, 2, "remote_cli"))

    assert len(controller.calls) == 1
    assert controller.calls[0]["source"] == "terminal"
    assert controller.calls[0]["reason"] == "operator_bait"
    assert events[-1]["event"] == "manual_bait_rejected"
    assert events[-1]["source"] == "remote_cli"


def test_terminal_b_is_one_queued_request_and_autorepeat_is_rejected(tmp_path: Path):
    config = replace(
        Config(),
        hardware=HardwareConfig(backend="lgpio", reward_active_level=1),
        paths=replace(
            Config().paths,
            reward_hardware_lock_path=tmp_path / "reward.lock",
            operator_control_socket=tmp_path / "operator.sock",
            operator_event_log=tmp_path / "events.jsonl",
        ),
    )
    events = []
    service = OperatorControlService(config, event_sink=events.append, backend=FakeBackend())

    assert service.submit_terminal_key("B")
    assert not service.submit_terminal_key("b")
    assert not service.submit_terminal_key("x")
    assert next(iter(service._pending)).source == "terminal"


def test_reward_hardware_ownership_blocks_second_owner(tmp_path: Path):
    path = tmp_path / "reward.lock"
    first = RewardHardwareOwnership(path)
    second = RewardHardwareOwnership(path)
    first.acquire()
    try:
        with pytest.raises(RewardHardwareBusyError):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_local_operator_endpoint_accepts_one_remote_bait(tmp_path: Path):
    path = tmp_path / "operator.sock"
    pending = []
    index = 0

    def enqueue(source):
        nonlocal index
        index += 1
        pending.append(source)
        return index

    endpoint = LocalOperatorControlEndpoint(path, enqueue)
    try:
        endpoint.start()
    except PermissionError as exc:
        if exc.errno == errno.EPERM:
            pytest.skip("sandbox disallows AF_UNIX filesystem sockets")
        raise
    response = {}

    def send():
        response.update(send_manual_bait(path))

    thread = threading.Thread(target=send)
    thread.start()
    deadline = time.monotonic() + 1
    while thread.is_alive() and time.monotonic() < deadline:
        endpoint.poll(0.01)
    thread.join()
    endpoint.close()

    assert response == {"ok": True, "request_index": 1, "source": "remote_cli", "status": "accepted"}
    assert pending == ["remote_cli"]


def test_gpio9_is_rejected_for_button_or_normal_outputs():
    with pytest.raises(WaterServiceError):
        validate_service_seconds(0)
    with pytest.raises(ValueError):
        config_from_mapping({"operator_controls": {"bait_button_gpio": 9}})
    with pytest.raises(ValueError, match="BCM GPIO9 is reserved for IRIG output"):
        config_from_mapping({"hardware": {"ttl_pin_bcm": 9}})
