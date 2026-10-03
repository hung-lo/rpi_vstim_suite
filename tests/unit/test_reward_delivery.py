import json
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
    RewardConfigurationError,
    RewardController,
    resolve_reward_duration,
)


class FakeClock:
    def __init__(self):
        self.now = 0

    def ns(self):
        self.now += 1_000
        return self.now

    def sleep(self, seconds):
        self.now += round(seconds * 1_000_000_000)


class FakeOutputBackend:
    def __init__(self, fail_active=False, clock=None):
        self.levels = []
        self.fail_active = fail_active
        self.clock = clock

    def set_level(self, role, level):
        self.levels.append((role, level))
        if self.fail_active and level == 1:
            raise RuntimeError("active write failed")
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


def test_reward_exception_returns_to_inactive_level():
    backend = FakeOutputBackend(fail_active=True)
    controller = RewardController(backend, active_config().hardware, duration_ms=50)

    with pytest.raises(RuntimeError, match="active write failed"):
        controller.deliver()

    assert backend.levels == [("reward_left", 1), ("reward_left", 0)]


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
