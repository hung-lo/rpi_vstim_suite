"""Native lgpio alert monitor for the canonical left/right lick inputs."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from .lick import LickClassifier


class LgpioLickError(RuntimeError):
    """Raised for lick-input ownership or alert failures."""


@dataclass(frozen=True)
class RawLickEdge:
    channel: str
    bcm_pin: int
    level: int
    timestamp_ns: int


@dataclass(frozen=True)
class ClassifiedLick:
    channel: str
    bcm_pin: int
    timestamp_ns: int
    raw_edge_index: int


class LickEventRecorder:
    """Separate raw-edge and classified-event sinks for validation/session logs."""

    def __init__(self) -> None:
        self.raw_edges: list[RawLickEdge] = []
        self.classified_licks: list[ClassifiedLick] = []

    def record_raw(self, edge: RawLickEdge) -> None:
        self.raw_edges.append(edge)

    def record_classified(self, lick: ClassifiedLick) -> None:
        self.classified_licks.append(lick)


class LgpioLickMonitor:
    """Own GPIO26/27 input alerts and classify each channel independently."""

    def __init__(
        self,
        hardware_config: Any,
        *,
        api: Any | None = None,
        on_raw_edge: Callable[[RawLickEdge], None] | None = None,
        on_classified: Callable[[ClassifiedLick], None] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._hardware_config = hardware_config
        self._api = api
        self._on_raw_edge = on_raw_edge
        self._on_classified = on_classified
        self._clock_ns = clock_ns
        self._handle: int | None = None
        self._callbacks: list[Any] = []
        self._claimed: dict[str, int] = {}
        self._pins = {
            "lick_left": hardware_config.lick_pin_bcm,
            "lick_right": hardware_config.lick_right_pin_bcm,
        }
        self._classifiers: dict[str, LickClassifier] = {}
        self._pin_to_channel = {pin: channel for channel, pin in self._pins.items()}
        self.raw_edge_count = {channel: 0 for channel in self._pins}
        self.classified_count = {channel: 0 for channel in self._pins}
        self.last_level = {channel: hardware_config.lick_idle_level for channel in self._pins}
        self.callback_errors: list[str] = []

    @property
    def started(self) -> bool:
        return self._handle is not None

    def diagnostics(self) -> dict[str, Any]:
        """Return nonblocking lifecycle/counter state for session diagnostics."""
        return {
            "started": self.started,
            "chip": self._hardware_config.chip,
            "handle_open": self._handle is not None,
            "claimed_pins": dict(self._claimed),
            "callback_registration_count": len(self._callbacks),
            "channels": dict(self._pins),
            "current_level": dict(self.last_level),
            "raw_edge_count": dict(self.raw_edge_count),
            "classified_count": dict(self.classified_count),
            "callback_error_count": len(self.callback_errors),
            "callback_errors": list(self.callback_errors),
        }

    def _load_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            import lgpio
        except ImportError as exc:  # pragma: no cover - Pi-only dependency
            raise LgpioLickError("the Pi lgpio module is not installed") from exc
        self._api = lgpio
        return lgpio

    @staticmethod
    def _check_result(result: Any, operation: str) -> None:
        if isinstance(result, int) and result < 0:
            raise LgpioLickError(f"{operation} failed with lgpio result {result}")

    def start(self) -> None:
        if self.started:
            return
        api = self._load_api()
        try:
            handle = api.gpiochip_open(self._hardware_config.chip)
            self._check_result(handle, "open GPIO chip for lick inputs")
            self._handle = handle
            for channel, pin in self._pins.items():
                self._check_result(
                    api.gpio_claim_alert(handle, pin, api.BOTH_EDGES, 0),
                    f"claim {channel} BCM GPIO{pin} alert",
                )
                self._claimed[channel] = pin
                initial = api.gpio_read(handle, pin)
                if initial != self._hardware_config.lick_idle_level:
                    raise LgpioLickError(
                        f"{channel} BCM GPIO{pin} is {initial}, expected idle "
                        f"{self._hardware_config.lick_idle_level}"
                    )
                self.last_level[channel] = initial
                self._classifiers[channel] = LickClassifier(
                    release_stable_ms=self._hardware_config.release_stable_ms,
                    min_classified_lick_interval_ms=self._hardware_config.min_classified_lick_interval_ms,
                    initial_level=initial,
                    initial_timestamp_ns=self._clock_ns(),
                )
                callback = api.callback(handle, pin, api.BOTH_EDGES, self._handle_alert)
                if callback is None:
                    raise LgpioLickError(f"register {channel} BCM GPIO{pin} callback")
                self._callbacks.append(callback)
            if len(self._callbacks) != len(self._pins):
                raise LgpioLickError("not all lick GPIO callbacks were registered")
        except BaseException:
            self._release_resources()
            raise

    def _handle_alert(self, _chip: int, pin: int, level: int, timestamp_ns: int) -> None:
        if level not in (0, 1):
            return
        channel = self._pin_to_channel.get(pin)
        if channel is None:
            return
        edge = RawLickEdge(channel, pin, level, timestamp_ns)
        self.raw_edge_count[channel] += 1
        self.last_level[channel] = level
        if self._on_raw_edge is not None:
            try:
                self._on_raw_edge(edge)
            except Exception as exc:  # noqa: BLE001 — callback failure is diagnostic
                self.callback_errors.append(f"raw callback: {exc}")
        classifier = self._classifiers[channel]
        if classifier.process_edge(level, timestamp_ns):
            classified = ClassifiedLick(
                channel,
                pin,
                timestamp_ns,
                self.raw_edge_count[channel] - 1,
            )
            self.classified_count[channel] += 1
            if self._on_classified is not None:
                try:
                    self._on_classified(classified)
                except Exception as exc:  # noqa: BLE001 — callback failure is diagnostic
                    self.callback_errors.append(f"classified callback: {exc}")

    def _release_resources(self) -> None:
        api = self._api
        handle = self._handle
        errors: list[BaseException] = []
        for callback in reversed(self._callbacks):
            try:
                callback.cancel()
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
        if api is not None and handle is not None:
            for pin in reversed(tuple(self._claimed.values())):
                try:
                    self._check_result(api.gpio_free(handle, pin), f"release lick GPIO{pin}")
                except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                    errors.append(exc)
            try:
                self._check_result(api.gpiochip_close(handle), "close lick GPIO chip")
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
        self._callbacks.clear()
        self._claimed.clear()
        self._handle = None
        if errors:
            raise LgpioLickError(str(errors[0]))

    def stop(self) -> None:
        if not self.started:
            return
        self._release_resources()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
