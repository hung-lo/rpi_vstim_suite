"""Configurable GPIO input and output boundaries."""

from .hardware.base import HardwareBackend
from .hardware.lgpio_backend import LgpioBackend
from .hardware.lgpio_lick import LgpioLickMonitor
from .hardware.models import OutputLineConfig
from .hardware.policy import reserved_gpio_message
from .hardware.simulated import SimulatedHardwareBackend

__all__ = [
    "HardwareBackend", "LgpioBackend", "LgpioLickMonitor", "OutputLineConfig",
    "SimulatedHardwareBackend", "reserved_gpio_message",
]
