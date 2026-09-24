from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareStatus:
    backend: str
    outputs_safe: bool
    worker_ready: bool

