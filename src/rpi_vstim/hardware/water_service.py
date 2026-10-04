"""Operator-only continuous water service and prime operations."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .policy import OPERATOR_BAIT_GPIO_BCM
from .reward import REWARD_GPIO_BCM, REWARD_ROLE

MAX_CONTINUOUS_WATER_OPEN_SECONDS = 300


class WaterServiceError(RuntimeError):
    """Raised for invalid or unsafe water-service operation."""


def validate_service_seconds(seconds: float) -> float:
    if not math.isfinite(seconds) or seconds <= 0:
        raise WaterServiceError("water prime seconds must be greater than zero")
    if seconds > MAX_CONTINUOUS_WATER_OPEN_SECONDS:
        raise WaterServiceError(
            f"water prime duration must be <= {MAX_CONTINUOUS_WATER_OPEN_SECONDS} seconds"
        )
    return float(seconds)


@dataclass(frozen=True)
class WaterServiceEvent:
    event: str
    monotonic_ns: int
    requested_seconds: float | None = None
    actual_open_interval_ns: int | None = None
    source: str = "service"
    gpio_bcm: int = REWARD_GPIO_BCM
    role: str = REWARD_ROLE

    def as_dict(self) -> dict[str, object]:
        return {
            "event": self.event,
            "monotonic_ns": self.monotonic_ns,
            "requested_seconds": self.requested_seconds,
            "actual_open_interval_ns": self.actual_open_interval_ns,
            "source": self.source,
            "gpio_bcm": self.gpio_bcm,
            "role": self.role,
        }


class WaterServiceController:
    """Drive GPIO19 for maintenance, never as a behavioral reward."""

    def __init__(
        self,
        backend: Any,
        hardware_config: Any,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        event_sink: Callable[[WaterServiceEvent], None] | None = None,
    ) -> None:
        self._backend = backend
        self._line = hardware_config.output_line(REWARD_ROLE)
        if self._line.bcm_pin != REWARD_GPIO_BCM:
            raise WaterServiceError("water service requires canonical reward_left BCM19")
        if self._line.active_level is None or self._line.active_level == self._line.initial_level:
            raise WaterServiceError("water service requires explicit reward electrical polarity")
        self._clock_ns = clock_ns
        self._sleep = sleep
        self._event_sink = event_sink
        self._state = "CLOSED"
        self._open_since_ns: int | None = None
        self._deadline_ns: int | None = None

    @property
    def open(self) -> bool:
        return self._state in {"OPEN", "OPEN_OR_UNKNOWN", "FAULT"}

    def _emit(self, event: WaterServiceEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def open_now(self, *, requested_seconds: float | None, source: str) -> None:
        if requested_seconds is not None:
            requested_seconds = validate_service_seconds(requested_seconds)
        if self.open:
            return
        now = self._clock_ns()
        self._backend.set_level(REWARD_ROLE, self._line.active_level)
        self._state = "OPEN"
        self._open_since_ns = now
        self._deadline_ns = (
            now + round(requested_seconds * 1_000_000_000)
            if requested_seconds is not None
            else now + MAX_CONTINUOUS_WATER_OPEN_SECONDS * 1_000_000_000
        )
        self._emit(WaterServiceEvent("water_service_open", now, requested_seconds, source=source))

    def close(self, *, source: str) -> None:
        if not self.open:
            return
        now = self._clock_ns()
        started = self._open_since_ns
        try:
            transition = self._backend.set_level(REWARD_ROLE, self._line.initial_level)
            readback = getattr(transition, "readback_level", None)
            if readback is not None and readback != self._line.initial_level:
                raise RuntimeError("water service inactive readback did not confirm baseline")
        except BaseException as first_error:  # noqa: BLE001 — cleanup must handle SIGINT/driver failures
            self._state = "OPEN_OR_UNKNOWN"
            try:
                retry = self._backend.set_level(REWARD_ROLE, self._line.initial_level)
                readback = getattr(retry, "readback_level", None)
                if readback is not None and readback != self._line.initial_level:
                    raise RuntimeError("water service cleanup readback did not confirm baseline")
            except BaseException as retry_error:  # noqa: BLE001 — retry must catch SIGINT/driver failures
                self._state = "FAULT"
                self._emit(
                    WaterServiceEvent(
                        "water_service_fault", now,
                        actual_open_interval_ns=now - started if started is not None else None,
                        source=source,
                    )
                )
                raise WaterServiceError(
                    f"water service inactive transition failed: {retry_error}"
                ) from first_error
            self._state = "CLOSED"
            self._open_since_ns = None
            self._deadline_ns = None
            self._emit(
                WaterServiceEvent(
                    "water_service_cleanup_retry", now,
                    actual_open_interval_ns=now - started if started is not None else None,
                    source=source,
                )
            )
            return
        else:
            self._state = "CLOSED"
            self._open_since_ns = None
            self._deadline_ns = None
            self._emit(
                WaterServiceEvent(
                    "water_service_close",
                    now,
                    actual_open_interval_ns=now - started if started is not None else None,
                    source=source,
                )
            )

    def prime(self, seconds: float, *, source: str = "terminal") -> tuple[WaterServiceEvent, ...]:
        seconds = validate_service_seconds(seconds)
        events: list[WaterServiceEvent] = []
        original_sink = self._event_sink
        def collect(event: WaterServiceEvent) -> None:
            events.append(event)
            if original_sink is not None:
                original_sink(event)

        self._event_sink = collect
        try:
            self.open_now(requested_seconds=seconds, source=source)
            while self.open:
                remaining_ns = (self._deadline_ns or self._clock_ns()) - self._clock_ns()
                if remaining_ns <= 0:
                    break
                self._sleep(remaining_ns / 1_000_000_000)
        finally:
            try:
                self.close(source=source)
            finally:
                self._event_sink = original_sink
        return tuple(events)

    def check_timeout(self, *, now_ns: int | None = None, source: str = "button_timeout") -> bool:
        if not self.open:
            return False
        now = self._clock_ns() if now_ns is None else now_ns
        if self._deadline_ns is not None and now >= self._deadline_ns:
            self.close(source=source)
            return True
        return False

    def close_if_active(self, *, source: str = "cleanup") -> None:
        self.close(source=source)


class WaterHoldStateMachine:
    """Debounce GPIO23 for physical hold-to-open service mode."""

    def __init__(
        self,
        service: WaterServiceController,
        *,
        idle_level: int,
        active_level: int,
        release_stable_ms: int = 25,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if idle_level == active_level or idle_level not in (0, 1) or active_level not in (0, 1):
            raise ValueError("water service button levels must be distinct LOW/HIGH values")
        if release_stable_ms <= 0:
            raise ValueError("water service release debounce must be positive")
        self.service = service
        self.idle_level = idle_level
        self.active_level = active_level
        self.release_stable_ns = release_stable_ms * 1_000_000
        self.clock_ns = clock_ns
        self._ready = True
        self._inactive_since_ns = clock_ns()
        self._timed_out = False
        self._current_level = idle_level

    def handle_level(self, level: int, timestamp_ns: int | None = None) -> None:
        if level not in (self.idle_level, self.active_level):
            raise ValueError("water service button level does not match configured polarity")
        timestamp_ns = self.clock_ns() if timestamp_ns is None else timestamp_ns
        if level == self.idle_level:
            self._current_level = level
            if self.service.open:
                self.service.close(source="button_release")
            if self._inactive_since_ns is None:
                self._inactive_since_ns = timestamp_ns
            self.check_release(now_ns=timestamp_ns)
            return
        self.check_release(now_ns=timestamp_ns)
        self._current_level = level
        if self._timed_out or not self._ready or self.service.open:
            return
        self.service.open_now(
            requested_seconds=float(MAX_CONTINUOUS_WATER_OPEN_SECONDS), source="button_hold"
        )
        self._ready = False
        self._inactive_since_ns = None

    def check_timeout(self, *, now_ns: int | None = None) -> bool:
        timed_out = self.service.check_timeout(now_ns=now_ns)
        if timed_out:
            self._timed_out = True
        return timed_out

    def check_release(self, *, now_ns: int | None = None) -> bool:
        """Re-arm after one stable idle edge, without requiring another edge."""
        if self._current_level != self.idle_level or self._inactive_since_ns is None:
            return False
        now = self.clock_ns() if now_ns is None else now_ns
        if now - self._inactive_since_ns < self.release_stable_ns:
            return False
        self._ready = True
        self._timed_out = False
        return True

    def close(self) -> None:
        self.service.close_if_active(source="cleanup")


def validate_service_button_gpio(pin: int) -> None:
    if pin != OPERATOR_BAIT_GPIO_BCM:
        raise WaterServiceError("water service button must use canonical BCM GPIO23")
