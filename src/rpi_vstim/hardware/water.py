"""Small, auditable water-delivery accounting helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass


class WaterLimitError(RuntimeError):
    """Raised when an operator-bait water budget would be exceeded."""


@dataclass
class WaterAccounting:
    """Track task and operator water without inferring service flow volume."""

    max_manual_bait_water_ul: float | None = None
    task_reward_water_ul: float = 0.0
    operator_bait_water_ul: float = 0.0

    def __post_init__(self) -> None:
        if self.max_manual_bait_water_ul is not None and (
            not math.isfinite(self.max_manual_bait_water_ul)
            or self.max_manual_bait_water_ul <= 0
        ):
            raise ValueError("max_manual_bait_water_ul must be finite and positive")

    @property
    def total_delivered_water_ul(self) -> float:
        return self.task_reward_water_ul + self.operator_bait_water_ul

    def record_task_reward(self, volume_ul: float) -> None:
        self._validate_volume(volume_ul)
        self.task_reward_water_ul += volume_ul

    def reserve_manual_bait(self, volume_ul: float) -> None:
        self._validate_volume(volume_ul)
        proposed = self.operator_bait_water_ul + volume_ul
        if (
            self.max_manual_bait_water_ul is not None
            and proposed > self.max_manual_bait_water_ul
        ):
            raise WaterLimitError(
                "manual bait water limit reached: "
                f"{proposed:g} uL would exceed {self.max_manual_bait_water_ul:g} uL"
            )
        self.operator_bait_water_ul = proposed

    def rollback_manual_bait(self, volume_ul: float) -> None:
        self._validate_volume(volume_ul)
        self.operator_bait_water_ul = max(0.0, self.operator_bait_water_ul - volume_ul)

    @staticmethod
    def _validate_volume(volume_ul: float) -> None:
        if not math.isfinite(volume_ul) or volume_ul <= 0:
            raise ValueError("water volume must be finite and positive")

    def as_dict(self) -> dict[str, float | None]:
        return {
            "task_reward_water_ul": self.task_reward_water_ul,
            "operator_bait_water_ul": self.operator_bait_water_ul,
            "total_delivered_water_ul": self.total_delivered_water_ul,
            "max_manual_bait_water_ul": self.max_manual_bait_water_ul,
        }
