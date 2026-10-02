from dataclasses import dataclass


@dataclass(frozen=True)
class OutputLineConfig:
    """Config-resolved electrical output line; polarity is deliberately optional."""

    role: str
    chip: int
    bcm_pin: int
    initial_level: int = 0
    active_level: int | None = None


@dataclass(frozen=True)
class HardwareStatus:
    backend: str
    outputs_safe: bool
    worker_ready: bool
