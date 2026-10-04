"""Single-open reward delivery and calibration-profile resolution."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rpi_vstim.core.config import Config

REWARD_ROLE = "reward_left"
REWARD_GPIO_BCM = 19
DELIVERY_MODE = "single_continuous_open"


class RewardConfigurationError(ValueError):
    """Raised when a reward cannot be made unambiguously safe."""


@dataclass(frozen=True)
class RewardEvent:
    event: str
    role: str
    gpio_bcm: int
    requested_open_duration_ms: float
    monotonic_ns: int
    actual_on_interval_ns: int | None = None
    command_id: str = ""
    session_id: str = ""
    trial_id: str = ""
    source: str = "task"
    reason: str = "task_reward"
    target_volume_ul: float | None = None
    calibration_id: str = ""
    calibration_sha256: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "role": self.role,
            "gpio_bcm": self.gpio_bcm,
            "requested_open_duration_ms": self.requested_open_duration_ms,
            "monotonic_ns": self.monotonic_ns,
            "actual_on_interval_ns": self.actual_on_interval_ns,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "trial_id": self.trial_id,
            "source": self.source,
            "reason": self.reason,
            "target_volume_ul": self.target_volume_ul,
            "calibration_id": self.calibration_id,
            "calibration_sha256": self.calibration_sha256,
        }


@dataclass(frozen=True)
class RewardDelivery:
    role: str
    gpio_bcm: int
    requested_open_duration_ms: float
    actual_on_interval_ns: int
    events: tuple[RewardEvent, ...]


@dataclass(frozen=True)
class RewardDurationResolution:
    open_duration_ms: float
    target_volume_ul: float | None = None
    calibration_id: str = ""
    calibration_path: Path | None = None
    calibration_sha256: str = ""
    calibration_created_at: str = ""
    delivery_mode: str = DELIVERY_MODE

    def provenance_dict(self) -> dict[str, object]:
        return {
            "reward_target_volume_ul": self.target_volume_ul,
            "reward_resolved_open_duration_ms": self.open_duration_ms,
            "reward_calibration_id": self.calibration_id,
            "reward_calibration_file_sha256": self.calibration_sha256,
            "reward_calibration_created_at": self.calibration_created_at,
            "reward_delivery_mode": self.delivery_mode,
        }


def _validate_output_config(config: Config) -> Any:
    line = config.hardware.output_line(REWARD_ROLE)
    if line.bcm_pin != REWARD_GPIO_BCM:
        raise RewardConfigurationError(
            f"{REWARD_ROLE} must resolve to BCM GPIO{REWARD_GPIO_BCM}, got GPIO{line.bcm_pin}"
        )
    if line.active_level is None:
        raise RewardConfigurationError(
            "reward_active_level is unset; actuator polarity must be validated before delivery"
        )
    if line.active_level == line.initial_level:
        raise RewardConfigurationError("reward active level must differ from its inactive level")
    return line


def resolve_reward_duration(
    config: Config,
    *,
    target_volume_ul: float | None = None,
) -> RewardDurationResolution:
    """Resolve and freeze one calibrated or explicit duration for a session."""
    _validate_output_config(config)
    hardware = config.hardware
    if target_volume_ul is None and hardware.reward_open_duration_ms is not None:
        return RewardDurationResolution(float(hardware.reward_open_duration_ms))
    profile_path = hardware.reward_calibration_profile
    target_volume = hardware.reward_target_ul if target_volume_ul is None else target_volume_ul
    if profile_path is None or target_volume is None:
        raise RewardConfigurationError(
            "configure reward_open_duration_ms or reward_target_ul with a calibration profile"
        )
    from .calibration import load_profile, profile_sha256

    profile = load_profile(profile_path)
    if profile.output_role not in {REWARD_ROLE, "reward"}:
        raise RewardConfigurationError(
            f"calibration output_role must be {REWARD_ROLE}, got {profile.output_role}"
        )
    if profile.gpio_bcm != REWARD_GPIO_BCM:
        raise RewardConfigurationError("calibration profile GPIO does not match reward_left BCM19")
    if profile.delivery_mode != DELIVERY_MODE:
        raise RewardConfigurationError("calibration profile is not single_continuous_open")
    try:
        duration = profile.resolve_duration_ms(float(target_volume))
    except ValueError as exc:
        raise RewardConfigurationError(str(exc)) from exc
    return RewardDurationResolution(
        duration,
        float(target_volume),
        profile.calibration_id,
        profile_path,
        profile_sha256(profile_path),
        profile.created_at,
    )


class RewardController:
    """Deliver one reward as one continuous active electrical interval."""

    def __init__(
        self,
        backend: Any,
        hardware_config: Any,
        *,
        duration_ms: float,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        event_sink: Callable[[RewardEvent], None] | None = None,
        resolution: RewardDurationResolution | None = None,
    ) -> None:
        self._backend = backend
        self._line = hardware_config.output_line(REWARD_ROLE)
        if self._line.bcm_pin != REWARD_GPIO_BCM:
            raise RewardConfigurationError("reward controller requires canonical BCM19")
        if self._line.active_level is None:
            raise RewardConfigurationError("reward active polarity is not configured")
        if self._line.active_level == self._line.initial_level:
            raise RewardConfigurationError("reward active and inactive levels must differ")
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise RewardConfigurationError("reward open duration must be finite and positive")
        self._duration_ms = float(duration_ms)
        self._clock_ns = clock_ns
        self._sleep = sleep
        self._event_sink = event_sink
        self._resolution = resolution or RewardDurationResolution(self._duration_ms)

    @classmethod
    def from_config(
        cls,
        backend: Any,
        config: Config,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        event_sink: Callable[[RewardEvent], None] | None = None,
    ) -> RewardController:
        resolution = resolve_reward_duration(config)
        controller = cls(
            backend,
            config.hardware,
            duration_ms=resolution.open_duration_ms,
            clock_ns=clock_ns,
            sleep=sleep,
            event_sink=event_sink,
            resolution=resolution,
        )
        controller._resolution = resolution
        return controller

    @property
    def duration_ms(self) -> float:
        return self._duration_ms

    @property
    def resolution(self) -> RewardDurationResolution:
        return self._resolution

    def _emit(self, event: RewardEvent, events: list[RewardEvent]) -> None:
        events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)

    def deliver(
        self,
        *,
        command_id: str = "",
        session_id: str = "",
        trial_id: str = "",
        source: str = "task",
        reason: str = "task_reward",
    ) -> RewardDelivery:
        events: list[RewardEvent] = []
        common = {
            "role": REWARD_ROLE,
            "gpio_bcm": self._line.bcm_pin,
            "requested_open_duration_ms": self._duration_ms,
            "command_id": command_id,
            "session_id": session_id,
            "trial_id": trial_id,
            "source": source,
            "reason": reason,
            "target_volume_ul": self._resolution.target_volume_ul,
            "calibration_id": self._resolution.calibration_id,
            "calibration_sha256": self._resolution.calibration_sha256,
        }
        self._emit(RewardEvent("reward_command", monotonic_ns=self._clock_ns(), **common), events)
        try:
            on_transition = self._backend.set_level(REWARD_ROLE, self._line.active_level)
            on_ns = getattr(on_transition, "completed_monotonic_ns", None)
            if on_ns is None:
                on_ns = self._clock_ns()
            self._emit(RewardEvent("reward_valve_on", monotonic_ns=on_ns, **common), events)
            deadline_ns = on_ns + round(self._duration_ms * 1_000_000)
            while (remaining_ns := deadline_ns - self._clock_ns()) > 0:
                self._sleep(remaining_ns / 1_000_000_000)
        except BaseException as exc:
            try:
                self._backend.set_level(REWARD_ROLE, self._line.initial_level)
            except BaseException as cleanup_error:
                raise exc from cleanup_error
            raise

        off_transition = self._backend.set_level(REWARD_ROLE, self._line.initial_level)
        off_ns = getattr(off_transition, "completed_monotonic_ns", None)
        if off_ns is None:
            off_ns = self._clock_ns()
        actual_ns = off_ns - on_ns
        self._emit(
            RewardEvent(
                "reward_valve_off",
                monotonic_ns=off_ns,
                actual_on_interval_ns=actual_ns,
                **common,
            ),
            events,
        )
        self._emit(
            RewardEvent(
                "reward_complete",
                monotonic_ns=self._clock_ns(),
                actual_on_interval_ns=actual_ns,
                **common,
            ),
            events,
        )
        return RewardDelivery(
            REWARD_ROLE,
            self._line.bcm_pin,
            self._duration_ms,
            actual_ns,
            tuple(events),
        )


def reward_provenance_json(resolution: RewardDurationResolution) -> str:
    return json.dumps(resolution.provenance_dict(), sort_keys=True)
