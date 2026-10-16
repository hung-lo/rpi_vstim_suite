import json
import threading
import time
from dataclasses import replace

import pytest

from rpi_vstim.core.config import Config, ConfigError, HardwareConfig, config_from_mapping
from rpi_vstim.core.session import new_session
from rpi_vstim.hardware.calibration import (
    CalibrationCondition,
    CalibrationError,
    CalibrationProfile,
    load_profile,
    mass_to_mean_volume_ul,
    profile_sha256,
    write_csv,
    write_png_curve,
    write_profile,
)
from rpi_vstim.hardware.reward import (
    BoundedEventHandoff,
    RewardArbiter,
    RewardBusyError,
    RewardConfigurationError,
    RewardController,
    RewardDeliveryError,
    RewardDurationResolution,
    resolve_reward_duration,
)
from rpi_vstim.hardware.water import WaterAccounting


class FakeClock:
    def __init__(self):
        self.now = 0

    def ns(self):
        self.now += 1_000
        return self.now

    def sleep(self, seconds):
        self.now += round(seconds * 1_000_000_000)


class FakeOutputBackend:
    def __init__(self, fail_active=False, fail_inactive=0, clock=None):
        self.levels = []
        self.fail_active = fail_active
        self.fail_inactive = fail_inactive
        self.clock = clock

    def set_level(self, role, level):
        self.levels.append((role, level))
        if self.fail_active and level == 1:
            raise RuntimeError("active write failed")
        if level == 0 and self.fail_inactive:
            self.fail_inactive -= 1
            raise RuntimeError("inactive write failed")
        timestamp = self.clock.ns() if self.clock is not None else len(self.levels) * 1_000
        return type("Transition", (), {"completed_monotonic_ns": timestamp})()


def active_config(**changes):
    values = {
        "reward_active_level": 1,
        "reward_open_duration_ms": 50.0,
        **changes,
    }
    return replace(
        Config(),
        hardware=replace(HardwareConfig(), **values),
    )


def test_one_reward_has_one_continuous_interval_and_four_events():
    clock = FakeClock()
    backend = FakeOutputBackend(clock=clock)
    events = []
    controller = RewardController(
        backend,
        active_config().hardware,
        duration_ms=50,
        clock_ns=clock.ns,
        sleep=clock.sleep,
        event_sink=events.append,
    )

    delivery = controller.deliver(command_id="cmd-1", session_id="s", trial_id="t")
    controller.close_events()

    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]
    assert [event.event for event in events] == [
        "reward_command",
        "reward_valve_on",
        "reward_valve_off",
        "reward_complete",
    ]
    assert delivery.actual_on_interval_ns >= 50_000_000
    assert events[2].actual_on_interval_ns == delivery.actual_on_interval_ns
    assert all(event.gpio_bcm == 19 for event in events)


def test_active_write_failure_is_conservatively_maybe_delivered():
    backend = FakeOutputBackend(fail_active=True)
    controller = RewardController(backend, active_config().hardware, duration_ms=1)

    with pytest.raises(RewardDeliveryError) as caught:
        controller.deliver()
    controller.close_events()

    error = caught.value
    assert error.activation_attempted
    assert error.may_have_activated
    assert not error.activation_confirmed
    assert error.inactive_confirmed
    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]


def test_keyboard_interrupt_during_open_is_wrapped_and_deactivates():
    clock = FakeClock()
    backend = FakeOutputBackend(clock=clock)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    controller = RewardController(
        backend,
        active_config().hardware,
        duration_ms=1000,
        clock_ns=clock.ns,
        sleep=interrupt,
    )
    with pytest.raises(RewardDeliveryError) as caught:
        controller.deliver()
    controller.close_events()

    assert isinstance(caught.value.original_error, KeyboardInterrupt)
    assert caught.value.may_have_activated
    assert caught.value.inactive_confirmed
    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]


def test_task_accounting_counts_maybe_delivered_reward():
    backend = FakeOutputBackend(fail_active=True)
    controller = RewardController(backend, active_config().hardware, duration_ms=1)
    accounting = WaterAccounting()
    arbiter = RewardArbiter(
        controller,
        task_resolution=RewardDurationResolution(1, 2.0),
        accounting=accounting,
    )

    with pytest.raises(RewardDeliveryError):
        arbiter.deliver_task(session_id="s")
    arbiter.close()

    assert accounting.task_reward_water_ul == 2.0


def test_failed_cleanup_retry_still_counts_task_water():
    backend = FakeOutputBackend(fail_inactive=2)
    controller = RewardController(backend, active_config().hardware, duration_ms=1)
    accounting = WaterAccounting()
    arbiter = RewardArbiter(
        controller,
        task_resolution=RewardDurationResolution(1, 2.0),
        accounting=accounting,
    )

    with pytest.raises(RewardDeliveryError) as caught:
        arbiter.deliver_task(session_id="s")
    arbiter.close()

    assert not caught.value.inactive_confirmed
    assert accounting.task_reward_water_ul == 2.0


def test_event_handoff_reports_drops_errors_and_close_failures():
    started = threading.Event()
    release = threading.Event()

    def blocked_sink(_event):
        started.set()
        release.wait(1)

    handoff = BoundedEventHandoff(blocked_sink, maxsize=1)
    assert handoff.publish("first")
    assert started.wait(1)
    assert handoff.publish("second")
    assert not handoff.publish("third")
    with pytest.raises(RuntimeError, match="did not close cleanly"):
        handoff.close(timeout_s=0.01)
    release.set()
    handoff.close(timeout_s=1)
    assert handoff.diagnostics()["dropped_count"] == 1

    errors = BoundedEventHandoff(lambda _event: (_ for _ in ()).throw(RuntimeError("sink")))
    assert errors.publish("event")
    errors.close(timeout_s=1)
    assert errors.diagnostics()["error_count"] == 1


def test_reward_exception_returns_to_inactive_level():
    backend = FakeOutputBackend(fail_active=True)
    controller = RewardController(backend, active_config().hardware, duration_ms=50)

    with pytest.raises(RuntimeError, match="active write failed"):
        controller.deliver()

    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]


def test_blocking_event_sink_is_not_in_the_valve_interval():
    backend = FakeOutputBackend()
    controller = RewardController(
        backend,
        active_config().hardware,
        duration_ms=1,
        event_sink=lambda _event: time.sleep(0.15),
    )
    started = time.monotonic()
    controller.deliver()
    elapsed = time.monotonic() - started
    controller.close_events()
    assert elapsed < 0.1
    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]


def test_inactive_failure_retries_and_reports_fault_state():
    backend = FakeOutputBackend(fail_inactive=1)
    controller = RewardController(backend, active_config().hardware, duration_ms=1)
    with pytest.raises(RewardDeliveryError) as caught:
        controller.deliver()
    controller.close_events()
    assert caught.value.activation_started
    assert caught.value.inactive_confirmed
    assert backend.levels == [("reward_left", 1), ("reward_left", 0), ("reward_left", 0)]


def test_reward_arbiter_rejects_manual_overlap_and_keeps_one_owner():
    class SlowController:
        resolution = RewardDurationResolution(1, 3.0)

        def __init__(self):
            self.active = False
            self.overlap = False
            self.started = threading.Event()
            self.release = threading.Event()

        def deliver(self, **kwargs):
            if self.active:
                self.overlap = True
            self.active = True
            self.started.set()
            self.release.wait(1)
            self.active = False
            return "delivery"

        def close_events(self):
            return None

    controller = SlowController()
    arbiter = RewardArbiter(
        controller,
        task_resolution=RewardDurationResolution(1, 1.0),
        manual_resolution=RewardDurationResolution(1, 3.0),
        accounting=WaterAccounting(),
    )
    thread = threading.Thread(target=arbiter.deliver_task)
    thread.start()
    assert controller.started.wait(1)
    with pytest.raises(RewardBusyError):
        arbiter.deliver_manual(command_id="manual", session_id="s")
    controller.release.set()
    thread.join()
    assert not controller.overlap


def test_missing_polarity_fails_closed():
    with pytest.raises(RewardConfigurationError, match="polarity"):
        RewardController(FakeOutputBackend(), HardwareConfig(), duration_ms=50)


def test_mass_conversion_and_profile_round_trip(tmp_path):
    assert mass_to_mean_volume_ul(10.0, 10.75, 100) == pytest.approx(7.5)
    profile = CalibrationProfile.create(
        calibration_id="rig-1-2026-10-03",
        rig_id="rig-1",
        conditions=(
            CalibrationCondition.measured(50, 100, 0, 0.5),
            CalibrationCondition.measured(100, 100, 0, 1.0),
        ),
        created_at="2026-10-03T00:00:00+00:00",
        software_commit="abc",
    )
    path = tmp_path / "profile.json"
    write_profile(profile, path)
    assert load_profile(path).as_dict() == profile.as_dict()
    digest = profile_sha256(path)
    write_profile(profile, path)
    assert profile_sha256(path) == digest
    write_csv(profile, tmp_path / "profile.csv")
    write_png_curve(profile, tmp_path / "profile.png")
    assert (tmp_path / "profile.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_corrupted_calibration_derived_fields_fail_closed(tmp_path):
    profile = CalibrationProfile.create(
        calibration_id="id",
        rig_id="rig",
        conditions=(
            CalibrationCondition.measured(50, 100, 0, 0.5),
            CalibrationCondition.measured(100, 100, 0, 1.0),
        ),
    )
    payload = profile.as_dict()
    payload["conditions"][0]["mean_volume_ul"] = 999.0
    path = tmp_path / "corrupt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CalibrationError, match="inconsistent mean_volume_ul"):
        load_profile(path)


def test_profile_interpolation_is_bounded():
    profile = CalibrationProfile.create(
        calibration_id="id",
        rig_id="rig",
        conditions=(
            CalibrationCondition.measured(50, 100, 0, 0.5),
            CalibrationCondition.measured(100, 100, 0, 1.0),
        ),
    )
    assert profile.resolve_duration_ms(7.5) == pytest.approx(75)
    with pytest.raises(CalibrationError, match="outside calibrated range"):
        profile.resolve_duration_ms(2)


def test_calibrated_duration_resolution_checks_role_and_profile(tmp_path):
    profile = CalibrationProfile.create(
        calibration_id="id",
        rig_id="rig",
        conditions=(
            CalibrationCondition.measured(50, 100, 0, 0.5),
            CalibrationCondition.measured(100, 100, 0, 1.0),
        ),
    )
    profile_path = tmp_path / "profile.json"
    write_profile(profile, profile_path)
    config = active_config(
        reward_open_duration_ms=None,
        reward_target_ul=7.5,
        reward_calibration_profile=profile_path,
    )
    resolution = resolve_reward_duration(config)
    assert resolution.open_duration_ms == pytest.approx(75)
    assert resolution.calibration_id == "id"
    assert resolution.calibration_sha256 == profile_sha256(profile_path)
    controller = RewardController.from_config(FakeOutputBackend(), config)
    assert controller.duration_ms == pytest.approx(75)
    assert controller.resolution.calibration_id == "id"

    with pytest.raises(RewardConfigurationError, match="outside calibrated range"):
        resolve_reward_duration(replace(config, hardware=replace(config.hardware, reward_target_ul=2)))
    with pytest.raises(RewardConfigurationError, match="GPIO19"):
        resolve_reward_duration(
            replace(config, hardware=replace(config.hardware, reward_pin_bcm=20))
        )


def test_legacy_six_pulse_config_is_rejected():
    with pytest.raises(ConfigError, match="legacy six-pulse"):
        config_from_mapping({"hardware": {"reward_num_pulses": 6}})
    with pytest.raises(ConfigError, match="legacy six-pulse"):
        config_from_mapping({"protocol": {"parameters": {"pulse_index": 1}}})


def test_invalid_mass_fails_closed():
    with pytest.raises(CalibrationError, match="below initial"):
        mass_to_mean_volume_ul(2, 1, 100)


def test_session_provenance_records_frozen_reward_resolution(tmp_path):
    profile = CalibrationProfile.create(
        calibration_id="id",
        rig_id="rig",
        conditions=(
            CalibrationCondition.measured(50, 100, 0, 0.5),
            CalibrationCondition.measured(100, 100, 0, 1.0),
        ),
    )
    profile_path = tmp_path / "profile.json"
    write_profile(profile, profile_path)
    config = active_config(
        reward_open_duration_ms=None,
        reward_target_ul=7.5,
        reward_calibration_profile=profile_path,
    )
    config = replace(config, paths=replace(config.paths, output_root=tmp_path / "sessions"))
    session = new_session(config, session_id="reward-provenance")
    session.write_initial_outputs()
    provenance = json.loads(
        (tmp_path / "sessions" / "reward-provenance" / "provenance.json").read_text()
    )
    assert provenance["reward_target_volume_ul"] == 7.5
    assert provenance["reward_resolved_open_duration_ms"] == pytest.approx(75)
    assert provenance["reward_calibration_id"] == "id"
    assert provenance["reward_calibration_file_sha256"] == profile_sha256(profile_path)
    session.close()


def test_session_persists_task_and_operator_water_accounting(tmp_path):
    config = replace(active_config(), paths=replace(Config().paths, output_root=tmp_path))
    session = new_session(config, session_id="water-accounting")
    session.write_initial_outputs()
    controller = RewardController(FakeOutputBackend(), config.hardware, duration_ms=1)
    arbiter = RewardArbiter(
        controller,
        task_resolution=RewardDurationResolution(1, 1.0),
        manual_resolution=RewardDurationResolution(1, 3.0),
        accounting=WaterAccounting(),
    )
    session.attach_reward_arbiter(arbiter)
    arbiter.deliver_task(session_id="water-accounting")
    arbiter.deliver_manual(command_id="manual", session_id="water-accounting")
    session.close()
    provenance = json.loads((tmp_path / "water-accounting" / "provenance.json").read_text())
    assert provenance["water_accounting"] == {
        "task_reward_water_ul": 1.0,
        "operator_bait_water_ul": 3.0,
        "total_delivered_water_ul": 4.0,
        "max_manual_bait_water_ul": None,
    }
