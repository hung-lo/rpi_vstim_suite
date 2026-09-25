from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class ProtocolInfo:
    name: str
    module: str
    status: str = "placeholder"


_PROTOCOLS = (
    ProtocolInfo("natural-images", "rpi_vstim.protocols.natural_images"),
    ProtocolInfo("reward-conditioning", "rpi_vstim.protocols.reward_conditioning"),
    ProtocolInfo("spout-training", "rpi_vstim.protocols.spout_training"),
    ProtocolInfo("drifting-gratings", "rpi_vstim.protocols.drifting_gratings"),
    ProtocolInfo("retinotopy", "rpi_vstim.protocols.retinotopy"),
)


def available_protocols() -> tuple[ProtocolInfo, ...]:
    return _PROTOCOLS


def get_protocol(name: str):
    for info in _PROTOCOLS:
        if info.name == name:
            return getattr(import_module(info.module), "protocol")
    raise KeyError(f"unknown protocol: {name}")
