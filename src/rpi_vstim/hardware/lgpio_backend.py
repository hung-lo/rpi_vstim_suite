"""Pi 5 GPIO output backend using the native ``lgpio`` bindings."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from .models import HardwareStatus, OutputLineConfig
from .ownership import RewardHardwareOwnership
from .policy import RESERVED_GPIO_BCM, reserved_gpio_message


class LgpioUnavailableError(RuntimeError):
    """Raised when the Pi-only lgpio bindings cannot be imported."""


class LgpioBackendError(RuntimeError):
    """Raised for GPIO ownership or electrical-line control failures."""


@dataclass(frozen=True)
class OutputTransition:
    role: str
    bcm_pin: int
    requested_level: int
    requested_monotonic_ns: int
    completed_monotonic_ns: int
    readback_level: int | None


@dataclass(frozen=True)
class OutputPulse:
    role: str
    target: OutputTransition
    baseline: OutputTransition
    requested_duration_s: float
    actual_duration_s: float


class LgpioBackend:
    """Config-driven, fail-closed owner for the candidate reward/vacuum lines."""

    _allowed_roles = frozenset({"reward", "vacuum"})

    def __init__(
        self,
        hardware_config: Any,
        *,
        roles: tuple[str, ...] = ("reward", "vacuum"),
        api: Any | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
        ownership_path: Path | None = Path("/tmp/rpi-vstim-reward.lock"),
    ) -> None:
        normalized = tuple(self._normalize_role(role) for role in roles)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("GPIO output roles must be unique and non-empty")
        if any(role not in self._allowed_roles for role in normalized):
            raise ValueError("only reward and vacuum GPIO outputs are supported")
        self._hardware_config = hardware_config
        self._roles = normalized
        self._api = api
        self._clock_ns = clock_ns
        self._sleep = sleep
        self._ownership = (
            RewardHardwareOwnership(ownership_path)
            if ownership_path is not None and "reward" in normalized
            else None
        )
        self._chip_handle: int | None = None
        self._claimed: dict[str, OutputLineConfig] = {}
        self.transitions: list[OutputTransition] = []
        self.warnings: list[str] = []

    @property
    def started(self) -> bool:
        return self._chip_handle is not None

    @staticmethod
    def _normalize_role(role: str) -> str:
        return {"suction": "vacuum", "reward_left": "reward"}.get(role, role)

    def _load_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            import lgpio
        except ImportError as exc:  # pragma: no cover - Pi-only dependency
            raise LgpioUnavailableError("the Pi lgpio module is not installed") from exc
        self._api = lgpio
        return lgpio

    def _line(self, role: str) -> OutputLineConfig:
        normalized = self._normalize_role(role)
        if normalized not in self._roles:
            raise LgpioBackendError(f"GPIO role is not owned by this session: {role}")
        line = self._hardware_config.output_line(normalized)
        if line.bcm_pin in RESERVED_GPIO_BCM:
            raise LgpioBackendError(reserved_gpio_message(line.bcm_pin))
        return line

    def line_config(self, role: str) -> OutputLineConfig:
        """Return the resolved line without exposing GPIO numbers to callers."""
        return self._line(role)

    @staticmethod
    def _level(level: int) -> int:
        if type(level) is not int or level not in (0, 1):
            raise ValueError("electrical GPIO level must be 0 (LOW) or 1 (HIGH)")
        return level

    @staticmethod
    def _check_result(result: Any, operation: str) -> None:
        if isinstance(result, int) and result < 0:
            raise LgpioBackendError(f"{operation} failed with lgpio result {result}")

    def start(self) -> HardwareStatus:
        if self.started:
            return HardwareStatus("lgpio", True, True)
        api = self._load_api()
        try:
            if self._ownership is not None:
                self._ownership.acquire()
            handle = api.gpiochip_open(self._hardware_config.chip)
            self._check_result(handle, "open GPIO chip")
            self._chip_handle = handle
            for role in self._roles:
                line = self._line(role)
                self._check_result(
                    api.gpio_claim_output(
                        self._chip_handle,
                        0,
                        line.bcm_pin,
                        line.initial_level,
                    ),
                    f"claim {role} BCM GPIO{line.bcm_pin}",
                )
                self._claimed[role] = line
        except (Exception, KeyboardInterrupt, SystemExit):
            self._release_resources()
            raise
        return HardwareStatus("lgpio", True, True)

    def _require_started(self) -> Any:
        if self._chip_handle is None:
            raise LgpioBackendError("GPIO backend is not started")
        return self._chip_handle

    def _readback(self, line: OutputLineConfig) -> int | None:
        try:
            value = self._load_api().gpio_read(self._require_started(), line.bcm_pin)
        except Exception as exc:  # noqa: BLE001 — readback is diagnostic only
            self.warnings.append(f"readback unavailable for {line.role}: {exc}")
            return None
        if value not in (0, 1):
            self.warnings.append(f"invalid readback for {line.role}: {value!r}")
            return None
        return value

    def set_level(self, role: str, level: int) -> OutputTransition:
        line = self._line(role)
        level = self._level(level)
        requested_ns = self._clock_ns()
        self._check_result(
            self._load_api().gpio_write(self._require_started(), line.bcm_pin, level),
            f"write {line.role} BCM GPIO{line.bcm_pin}",
        )
        completed_ns = self._clock_ns()
        transition = OutputTransition(
            line.role, line.bcm_pin, level, requested_ns, completed_ns, self._readback(line)
        )
        self.transitions.append(transition)
        return transition

    def read_level(self, role: str) -> int | None:
        return self._readback(self._line(role))

    def pulse(
        self,
        role: str,
        target_level: int,
        duration_s: float,
        *,
        baseline_level: int | None = None,
    ) -> OutputPulse:
        if not math.isfinite(duration_s) or duration_s <= 0:
            raise ValueError("pulse duration must be finite and positive")
        line = self._line(role)
        baseline = line.initial_level if baseline_level is None else self._level(baseline_level)
        target = self.set_level(line.role, target_level)
        self._sleep(duration_s)
        restored = self.set_level(line.role, baseline)
        return OutputPulse(
            line.role,
            target,
            restored,
            duration_s,
            (restored.completed_monotonic_ns - target.completed_monotonic_ns) / 1_000_000_000,
        )

    def safe(self) -> None:
        for role in self._roles:
            self.set_level(role, self._hardware_config.output_line(role).initial_level)

    def _release_resources(self) -> None:
        api = self._api
        handle = self._chip_handle
        errors: list[BaseException] = []
        if api is not None and handle is not None:
            for line in reversed(tuple(self._claimed.values())):
                try:
                    self._check_result(api.gpio_free(handle, line.bcm_pin), f"release {line.role}")
                except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                    errors.append(exc)
            try:
                self._check_result(api.gpiochip_close(handle), "close GPIO chip")
            except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
                errors.append(exc)
        self._claimed.clear()
        self._chip_handle = None
        if self._ownership is not None:
            self._ownership.release()
        if errors:
            raise LgpioBackendError(str(errors[0]))

    def stop(self) -> None:
        if not self.started:
            return
        failure: BaseException | None = None
        try:
            self.safe()
        except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
            failure = exc
        try:
            self._release_resources()
        except BaseException as exc:  # noqa: BLE001 — cleanup must survive SIGINT
            if failure is None:
                failure = exc
        if failure is not None:
            raise failure

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
