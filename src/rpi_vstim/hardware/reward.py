"""Single-open reward delivery and calibration-profile resolution."""

from __future__ import annotations

import json
import math
import queue
import threading
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


class RewardDeliveryError(RuntimeError):
    """A reward failed; fields describe whether GPIO19 may have opened."""

    def __init__(
        self,
        message: str,
        *,
        activation_started: bool,
        inactive_confirmed: bool,
        cleanup_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.activation_started = activation_started
        self.inactive_confirmed = inactive_confirmed
        self.cleanup_error = cleanup_error


class RewardBusyError(RuntimeError):
    """A manual request arrived while another reward was active."""


class SimulatedRewardBackend:
    """Small output backend for session/runtime tests; never touches GPIO."""

    def __init__(self) -> None:
        self.transitions: list[tuple[str, int]] = []
        self.levels: dict[str, int] = {}

    def set_level(self, role: str, level: int) -> Any:
        self.transitions.append((role, level))
        self.levels[role] = level
        return type("Transition", (), {"completed_monotonic_ns": time.monotonic_ns(),
                                        "readback_level": level})()


class BoundedEventHandoff:
    """Nonblocking event enqueue with a background writer."""

    _STOP = object()

    def __init__(self, sink: Callable[[Any], None], *, maxsize: int = 256):
        if maxsize <= 0:
            raise ValueError("event handoff maxsize must be positive")
        self._sink = sink
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self.dropped_count = 0
        self.error_count = 0
        self._thread = threading.Thread(target=self._run, name="rpi-vstim-events", daemon=True)
        self._thread.start()

    def publish(self, event: Any) -> bool:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_count += 1
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if event is self._STOP:
                self._queue.task_done()
                break
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 — writer diagnostics must not reach GPIO timing
                self.error_count += 1
            finally:
                self._queue.task_done()

    def flush(self, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.001)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout_s: float = 5.0) -> None:
        self.flush(timeout_s)
        self._stop.set()
        self._thread.join(timeout=max(0.0, timeout_s))


def ensure_event_handoff(
    sink: Callable[[Any], None] | BoundedEventHandoff | None,
) -> BoundedEventHandoff | None:
    if sink is None or isinstance(sink, BoundedEventHandoff):
        return sink
    return BoundedEventHandoff(sink)


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
    error: str = ""
    inactive_confirmed: bool | None = None

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
            "error": self.error,
            "inactive_confirmed": self.inactive_confirmed,
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
        self._event_handoff = ensure_event_handoff(event_sink)
        self._delivery_lock = threading.Lock()
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
        if self._event_handoff is not None:
            self._event_handoff.publish(event)

    @property
    def event_handoff(self) -> BoundedEventHandoff | None:
        return self._event_handoff

    def close_events(self) -> None:
        if self._event_handoff is not None:
            self._event_handoff.close()

    def _deactivate(self) -> tuple[Any | None, BaseException | None]:
        try:
            transition = self._backend.set_level(REWARD_ROLE, self._line.initial_level)
            readback = getattr(transition, "readback_level", None)
            if readback is not None and readback != self._line.initial_level:
                raise RuntimeError("reward inactive readback did not confirm the configured baseline")
            return transition, None
        except BaseException as exc:  # noqa: BLE001 — cleanup must be fail-safe
            return None, exc

    def deliver(
        self,
        *,
        command_id: str = "",
        session_id: str = "",
        trial_id: str = "",
        source: str = "task",
        reason: str = "task_reward",
        duration_ms: float | None = None,
        resolution: RewardDurationResolution | None = None,
    ) -> RewardDelivery:
        if duration_ms is None:
            duration_ms = self._duration_ms
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise RewardConfigurationError("reward open duration must be finite and positive")
        selected_resolution = resolution or self._resolution
        with self._delivery_lock:
            return self._deliver_locked(
                command_id=command_id,
                session_id=session_id,
                trial_id=trial_id,
                source=source,
                reason=reason,
                duration_ms=float(duration_ms),
                resolution=selected_resolution,
            )

    def _deliver_locked(
        self,
        *,
        command_id: str,
        session_id: str,
        trial_id: str,
        source: str,
        reason: str,
        duration_ms: float,
        resolution: RewardDurationResolution,
    ) -> RewardDelivery:
        events: list[RewardEvent] = []
        common = {
            "role": REWARD_ROLE,
            "gpio_bcm": self._line.bcm_pin,
            "requested_open_duration_ms": duration_ms,
            "command_id": command_id,
            "session_id": session_id,
            "trial_id": trial_id,
            "source": source,
            "reason": reason,
            "target_volume_ul": resolution.target_volume_ul,
            "calibration_id": resolution.calibration_id,
            "calibration_sha256": resolution.calibration_sha256,
        }
        self._emit(RewardEvent("reward_command", monotonic_ns=self._clock_ns(), **common), events)
        activation_started = False
        on_ns = self._clock_ns()
        try:
            on_transition = self._backend.set_level(REWARD_ROLE, self._line.active_level)
            activation_started = True
            on_ns = getattr(on_transition, "completed_monotonic_ns", None)
            if on_ns is None:
                on_ns = self._clock_ns()
            self._emit(RewardEvent("reward_valve_on", monotonic_ns=on_ns, **common), events)
            deadline_ns = on_ns + round(duration_ms * 1_000_000)
            while (remaining_ns := deadline_ns - self._clock_ns()) > 0:
                self._sleep(remaining_ns / 1_000_000_000)
        except KeyboardInterrupt:
            _transition, cleanup_error = self._deactivate()
            if cleanup_error is not None:
                raise cleanup_error
            raise
        except Exception as exc:
            _transition, cleanup_error = self._deactivate()
            raise RewardDeliveryError(
                str(exc),
                activation_started=activation_started,
                inactive_confirmed=cleanup_error is None,
                cleanup_error=cleanup_error,
            ) from exc

        try:
            off_transition = self._backend.set_level(REWARD_ROLE, self._line.initial_level)
            readback = getattr(off_transition, "readback_level", None)
            if readback is not None and readback != self._line.initial_level:
                raise RuntimeError("reward inactive readback did not confirm the configured baseline")
        except BaseException as first_error:
            _retry_transition, retry_error = self._deactivate()
            inactive_confirmed = retry_error is None
            self._emit(
                RewardEvent(
                    "reward_cleanup_retry" if inactive_confirmed else "reward_fault",
                    monotonic_ns=self._clock_ns(),
                    actual_on_interval_ns=self._clock_ns() - on_ns,
                    error=str(first_error if retry_error is None else retry_error),
                    inactive_confirmed=inactive_confirmed,
                    **common,
                ),
                events,
            )
            if isinstance(first_error, KeyboardInterrupt) and inactive_confirmed:
                raise
            raise RewardDeliveryError(
                "reward valve inactive transition failed",
                activation_started=True,
                inactive_confirmed=inactive_confirmed,
                cleanup_error=retry_error or first_error,
            ) from first_error

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
            duration_ms,
            actual_ns,
            tuple(events),
        )


class RewardArbiter:
    """One session owner that serializes task and operator reward requests."""

    def __init__(
        self,
        controller: RewardController,
        *,
        task_resolution: RewardDurationResolution | None = None,
        manual_resolution: RewardDurationResolution | None = None,
        accounting: Any | None = None,
    ) -> None:
        self.controller = controller
        self.task_resolution = task_resolution
        self.manual_resolution = manual_resolution
        self.accounting = accounting
        self._lock = threading.Lock()

    @classmethod
    def from_config(
        cls,
        backend: Any,
        config: Config,
        *,
        session_id: str = "",
        event_sink: Callable[[RewardEvent], None] | BoundedEventHandoff | None = None,
    ) -> RewardArbiter:
        task_resolution = None
        if (
            config.hardware.reward_open_duration_ms is not None
            or config.hardware.reward_target_ul is not None
        ):
            task_resolution = resolve_reward_duration(config)
        manual_resolution = None
        if config.operator_controls.manual_bait_enabled:
            manual_resolution = resolve_reward_duration(
                config,
                target_volume_ul=config.operator_controls.bait_reward_ul,
            )
        resolution = task_resolution or manual_resolution
        if resolution is None:
            raise RewardConfigurationError("session has no configured reward delivery")
        controller = RewardController(
            backend,
            config.hardware,
            duration_ms=resolution.open_duration_ms,
            event_sink=event_sink,
            resolution=resolution,
        )
        from .water import WaterAccounting

        return cls(
            controller,
            task_resolution=task_resolution,
            manual_resolution=manual_resolution,
            accounting=WaterAccounting(config.operator_controls.max_manual_bait_water_ul),
        )

    @property
    def event_handoff(self) -> BoundedEventHandoff | None:
        return self.controller.event_handoff

    def deliver_task(
        self,
        *,
        command_id: str = "",
        session_id: str = "",
        trial_id: str = "",
    ) -> RewardDelivery:
        if self.task_resolution is None:
            raise RewardConfigurationError("task reward is not configured for this session")
        with self._lock:
            try:
                delivery = self.controller.deliver(
                    command_id=command_id,
                    session_id=session_id,
                    trial_id=trial_id,
                    source="task",
                    reason="task_reward",
                    duration_ms=self.task_resolution.open_duration_ms,
                    resolution=self.task_resolution,
                )
            except RewardDeliveryError as exc:
                if (
                    self.accounting is not None
                    and self.task_resolution.target_volume_ul is not None
                    and exc.activation_started
                ):
                    self.accounting.record_task_reward(self.task_resolution.target_volume_ul)
                raise
            if self.accounting is not None and self.task_resolution.target_volume_ul is not None:
                self.accounting.record_task_reward(self.task_resolution.target_volume_ul)
            return delivery

    def deliver_manual(
        self,
        *,
        command_id: str,
        session_id: str,
        trial_id: str = "",
        source: str = "operator",
    ) -> RewardDelivery:
        if self.manual_resolution is None:
            raise RewardConfigurationError("manual bait is not configured for this session")
        if not self._lock.acquire(blocking=False):
            raise RewardBusyError("manual bait rejected while a reward is active")
        volume = self.manual_resolution.target_volume_ul
        reserved = False
        try:
            if self.accounting is not None:
                if volume is None:
                    raise RewardConfigurationError("manual bait requires a calibrated target volume")
                self.accounting.reserve_manual_bait(volume)
                reserved = True
            try:
                return self.controller.deliver(
                    command_id=command_id,
                    session_id=session_id,
                    trial_id=trial_id,
                    source=source,
                    reason="operator_bait",
                    duration_ms=self.manual_resolution.open_duration_ms,
                    resolution=self.manual_resolution,
                )
            except RewardDeliveryError as exc:
                if reserved and not exc.activation_started:
                    self.accounting.rollback_manual_bait(volume)
                raise
            except BaseException:
                # Unknown interruption after handoff is conservatively counted.
                raise
        finally:
            self._lock.release()

    def close(self) -> None:
        self.controller.close_events()


def reward_provenance_json(resolution: RewardDurationResolution) -> str:
    return json.dumps(resolution.provenance_dict(), sort_keys=True)
