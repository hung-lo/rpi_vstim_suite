"""Legacy opt-in GPIO23 operator bait input with explicit polarity and re-arm state."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from .policy import OPERATOR_BAIT_GPIO_BCM
from .reward import (
    RewardArbiter,
    RewardController,
    RewardDelivery,
    RewardDeliveryError,
    resolve_reward_duration,
)
from .water import WaterAccounting, WaterLimitError


class OperatorBaitError(RuntimeError):
    """Raised for operator-bait input ownership or configuration failures."""


@dataclass(frozen=True)
class RawOperatorBaitEdge:
    bcm_pin: int
    level: int
    timestamp_ns: int
    raw_edge_index: int


@dataclass(frozen=True)
class ManualBaitRequest:
    bcm_pin: int | None
    timestamp_ns: int
    request_index: int
    source: str = "physical_button"


class OperatorBaitStateMachine:
    """Emit one request per pressed-and-released button contact."""

    def __init__(
        self,
        *,
        idle_level: int,
        active_level: int,
        release_stable_ms: int = 25,
        min_interval_ms: int = 1000,
        initial_level: int | None = None,
        initial_timestamp_ns: int = 0,
        bcm_pin: int = OPERATOR_BAIT_GPIO_BCM,
    ) -> None:
        if idle_level not in (0, 1) or active_level not in (0, 1):
            raise ValueError("operator bait levels must be 0 or 1")
        if idle_level == active_level:
            raise ValueError("operator bait idle and active levels must differ")
        if release_stable_ms <= 0 or min_interval_ms <= 0:
            raise ValueError("operator bait timing settings must be positive")
        if initial_level is None:
            initial_level = idle_level
        if initial_level not in (idle_level, active_level):
            raise ValueError("operator bait initial level must match idle or active")
        self.idle_level = idle_level
        self.active_level = active_level
        self.release_stable_ns = release_stable_ms * 1_000_000
        self.min_interval_ns = min_interval_ms * 1_000_000
        self.bcm_pin = bcm_pin
        self._latched = initial_level == active_level
        self._inactive_since_ns = initial_timestamp_ns if self._latched is False else None
        self._last_request_ns: int | None = None
        self._last_edge_ns: int | None = None
        self._request_count = 0

    @property
    def latched(self) -> bool:
        return self._latched

    def process_edge(self, level: int, timestamp_ns: int) -> ManualBaitRequest | None:
        if level not in (self.idle_level, self.active_level):
            raise ValueError("operator bait edge level does not match configured polarity")
        if self._last_edge_ns is not None and timestamp_ns < self._last_edge_ns:
            raise ValueError("operator bait edge timestamps must be monotonic")
        self._last_edge_ns = timestamp_ns

        if level == self.idle_level:
            if self._latched and self._inactive_since_ns is None:
                self._inactive_since_ns = timestamp_ns
            return None

        if self._latched:
            if (
                self._inactive_since_ns is None
                or timestamp_ns - self._inactive_since_ns < self.release_stable_ns
            ):
                return None
            self._latched = False
            self._inactive_since_ns = None

        self._latched = True
        if (
            self._last_request_ns is not None
            and timestamp_ns - self._last_request_ns < self.min_interval_ns
        ):
            return None
        self._last_request_ns = timestamp_ns
        self._request_count += 1
        return ManualBaitRequest(self.bcm_pin, timestamp_ns, self._request_count)


class LgpioOperatorBaitMonitor:
    """Own only configured GPIO23 as an input alert; never writes a GPIO."""

    def __init__(
        self,
        config: Any,
        *,
        api: Any | None = None,
        on_raw_edge: Callable[[RawOperatorBaitEdge], None] | None = None,
        on_request: Callable[[ManualBaitRequest], None] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        controls = config.operator_controls
        if not controls.bait_button_enabled:
            raise OperatorBaitError("operator bait button is disabled")
        if controls.bait_button_gpio != OPERATOR_BAIT_GPIO_BCM:
            raise OperatorBaitError("operator bait button must use canonical BCM GPIO23")
        if controls.bait_button_idle_level is None or controls.bait_button_active_level is None:
            raise OperatorBaitError("operator bait button polarity must be explicit")
        self._config = config
        self._controls = controls
        self._api = api
        self._on_raw_edge = on_raw_edge
        self._on_request = on_request
        self._clock_ns = clock_ns
        self._handle: int | None = None
        self._callback: Any | None = None
        self.raw_edge_count = 0
        self.last_level = controls.bait_button_idle_level
        self.callback_errors: list[str] = []
        self._state: OperatorBaitStateMachine | None = None

    @property
    def started(self) -> bool:
        return self._handle is not None

    def _load_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            import lgpio
        except ImportError as exc:  # pragma: no cover - Pi-only dependency
            raise OperatorBaitError("the Pi lgpio module is not installed") from exc
        self._api = lgpio
        return lgpio

    @staticmethod
    def _check_result(result: Any, operation: str) -> None:
        if isinstance(result, int) and result < 0:
            raise OperatorBaitError(f"{operation} failed with lgpio result {result}")

    def start(self) -> None:
        if self.started:
            return
        api = self._load_api()
        pin = self._controls.bait_button_gpio
        try:
            handle = api.gpiochip_open(self._config.hardware.chip)
            self._check_result(handle, "open GPIO chip for operator bait button")
            self._handle = handle
            self._check_result(
                api.gpio_claim_alert(handle, pin, api.BOTH_EDGES, 0),
                f"claim operator bait BCM GPIO{pin} alert",
            )
            initial = api.gpio_read(handle, pin)
            if initial != self._controls.bait_button_idle_level:
                raise OperatorBaitError(
                    f"operator bait BCM GPIO{pin} is {initial}, expected idle "
                    f"{self._controls.bait_button_idle_level}"
                )
            self.last_level = initial
            self._state = OperatorBaitStateMachine(
                idle_level=self._controls.bait_button_idle_level,
                active_level=self._controls.bait_button_active_level,
                release_stable_ms=self._controls.bait_button_release_stable_ms,
                min_interval_ms=self._controls.minimum_interval_ms,
                initial_level=initial,
                initial_timestamp_ns=self._clock_ns(),
                bcm_pin=pin,
            )
            self._callback = api.callback(handle, pin, api.BOTH_EDGES, self._handle_alert)
        except BaseException:
            self._release_resources()
            raise

    def _handle_alert(self, _chip: int, pin: int, level: int, timestamp_ns: int) -> None:
        if pin != self._controls.bait_button_gpio or level not in (0, 1):
            return
        self.raw_edge_count += 1
        self.last_level = level
        edge = RawOperatorBaitEdge(pin, level, timestamp_ns, self.raw_edge_count - 1)
        if self._on_raw_edge is not None:
            try:
                self._on_raw_edge(edge)
            except Exception as exc:  # noqa: BLE001 — callback failure is diagnostic
                self.callback_errors.append(f"raw callback: {exc}")
        if self._state is None:
            return
        try:
            request = self._state.process_edge(level, timestamp_ns)
        except ValueError as exc:
            self.callback_errors.append(f"state machine: {exc}")
            return
        if request is not None and self._on_request is not None:
            try:
                self._on_request(request)
            except Exception as exc:  # noqa: BLE001 — callback failure is diagnostic
                self.callback_errors.append(f"request callback: {exc}")

    def _release_resources(self) -> None:
        api = self._api
        handle = self._handle
        errors: list[BaseException] = []
        if self._callback is not None:
            try:
                self._callback.cancel()
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
        if api is not None and handle is not None:
            try:
                self._check_result(
                    api.gpio_free(handle, self._controls.bait_button_gpio),
                    "release operator bait GPIO23",
                )
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
            try:
                self._check_result(api.gpiochip_close(handle), "close operator bait GPIO chip")
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
        self._callback = None
        self._handle = None
        self._state = None
        if errors:
            raise OperatorBaitError(str(errors[0]))

    def stop(self) -> None:
        if self.started:
            self._release_resources()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()


class ManualBaitService:
    """Turn a debounced GPIO23 request into one normal calibrated reward."""

    def __init__(
        self,
        controller: RewardController | None = None,
        *,
        arbiter: RewardArbiter | None = None,
        session_id: str = "",
        event_sink: Callable[[Any], None] | None = None,
        water_accounting: WaterAccounting | None = None,
    ) -> None:
        if controller is None and arbiter is None:
            raise OperatorBaitError("manual bait requires a reward controller or session arbiter")
        self.controller = controller
        self.arbiter = arbiter
        self.session_id = session_id
        self._event_sink = event_sink
        self.water_accounting = water_accounting

    @classmethod
    def from_config(
        cls,
        backend: Any,
        config: Any,
        *,
        session_id: str = "",
        event_sink: Callable[[Any], None] | None = None,
        water_accounting: WaterAccounting | None = None,
    ) -> ManualBaitService:
        controls = config.operator_controls
        if not controls.manual_bait_enabled or controls.bait_reward_ul is None:
            raise OperatorBaitError("manual bait is disabled or lacks bait_reward_ul")
        resolution = resolve_reward_duration(config, target_volume_ul=controls.bait_reward_ul)
        return cls(
            RewardController(
                backend,
                config.hardware,
                duration_ms=resolution.open_duration_ms,
                event_sink=event_sink,
                resolution=resolution,
            ),
            session_id=session_id,
            event_sink=event_sink,
            water_accounting=water_accounting or WaterAccounting(
                controls.max_manual_bait_water_ul
            ),
        )

    def handle_request(self, request: ManualBaitRequest) -> RewardDelivery:
        if request.source not in {"physical_button", "terminal", "remote_cli"}:
            raise OperatorBaitError(f"unsupported manual bait source: {request.source}")
        if request.source == "physical_button" and request.bcm_pin != OPERATOR_BAIT_GPIO_BCM:
            raise OperatorBaitError("manual bait request is not from canonical BCM GPIO23")
        if request.source != "physical_button" and request.bcm_pin not in (None, 0):
            raise OperatorBaitError("non-button manual bait requests must not claim a GPIO")
        resolution = (
            self.arbiter.manual_resolution
            if self.arbiter is not None
            else getattr(self.controller, "resolution", None)
        )
        target_volume_ul = getattr(resolution, "target_volume_ul", None)
        duration_ms = getattr(resolution, "open_duration_ms", None)
        if duration_ms is None:
            duration_ms = getattr(self.controller, "duration_ms", None) if self.controller else None
        if self.arbiter is None and self.water_accounting is not None:
            if target_volume_ul is None:
                raise OperatorBaitError(
                    "manual bait water accounting requires a calibrated target volume"
                )
            try:
                self.water_accounting.reserve_manual_bait(target_volume_ul)
            except WaterLimitError as exc:
                if self._event_sink is not None:
                    self._event_sink(
                        {
                            "event": "manual_bait_rejected",
                            "source": request.source,
                            "reason": str(exc),
                            "target_volume_ul": target_volume_ul,
                            "monotonic_ns": request.timestamp_ns,
                        }
                    )
                raise
        if self._event_sink is not None:
            try:
                self._event_sink(
                    {
                        "event": "manual_bait_request",
                        "role": "operator_bait_button",
                        "gpio_bcm": request.bcm_pin,
                        "monotonic_ns": request.timestamp_ns,
                        "request_index": request.request_index,
                        "session_id": self.session_id,
                        "source": request.source,
                        "reason": "operator_bait",
                        "target_volume_ul": target_volume_ul,
                        "resolved_open_duration_ms": duration_ms,
                        "calibration_id": getattr(resolution, "calibration_id", ""),
                        "calibration_sha256": getattr(resolution, "calibration_sha256", ""),
                    }
                )
            except BaseException:
                if self.arbiter is None and self.water_accounting is not None and target_volume_ul is not None:
                    self.water_accounting.rollback_manual_bait(target_volume_ul)
                raise
        try:
            if self.arbiter is not None:
                return self.arbiter.deliver_manual(
                    command_id=f"manual-bait-{request.request_index:06d}",
                    session_id=self.session_id,
                    source=request.source,
                )
            return self.controller.deliver(
                command_id=f"manual-bait-{request.request_index:06d}",
                session_id=self.session_id,
                source=request.source,
                reason="operator_bait",
            )
        except RewardDeliveryError as exc:
            if (
                self.arbiter is None
                and self.water_accounting is not None
                and target_volume_ul is not None
                and not exc.activation_started
            ):
                self.water_accounting.rollback_manual_bait(target_volume_ul)
            if exc.activation_started and self._event_sink is not None:
                self._event_sink(
                    {
                        "event": "manual_bait_partial_delivery",
                        "source": request.source,
                        "target_volume_ul": target_volume_ul,
                        "monotonic_ns": request.timestamp_ns,
                        "reason": str(exc),
                    }
                )
            raise

    def close(self) -> None:
        if self.arbiter is None and self.controller is not None:
            self.controller.close_events()
