from __future__ import annotations

from typing import Protocol

from .models import HardwareStatus


class HardwareBackend(Protocol):
    def start(self) -> HardwareStatus: ...
    def safe(self) -> None: ...
    def stop(self) -> None: ...

