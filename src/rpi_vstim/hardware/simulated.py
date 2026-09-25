from __future__ import annotations

from .models import HardwareStatus


class SimulatedHardwareBackend:
    """Safe backend for desktop tests; it has no GPIO imports or side effects."""

    def __init__(self) -> None:
        self.started = False
        self.outputs_safe = True

    def start(self) -> HardwareStatus:
        self.started = True
        self.outputs_safe = True
        return HardwareStatus("simulated", True, True)

    def safe(self) -> None:
        self.outputs_safe = True

    def stop(self) -> None:
        self.safe()
        self.started = False

