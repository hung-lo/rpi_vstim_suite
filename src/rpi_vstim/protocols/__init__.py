from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class ProtocolInfo:
    name: str
    module: str
    status: str = "placeholder"


_PROTOCOLS = (
    ProtocolInfo("natural-images", "rpi_vstim.protocols.natural_images", "software-groundwork"),
    ProtocolInfo("reward-conditioning", "rpi_vstim.protocols.reward_conditioning", "software-groundwork"),
    ProtocolInfo("spout-training", "rpi_vstim.protocols.spout_training", "software-groundwork"),
    ProtocolInfo("drifting-gratings", "rpi_vstim.protocols.drifting_gratings", "software-implemented; Pi validation pending"),
    ProtocolInfo("retinotopy", "rpi_vstim.protocols.retinotopy", "software-implemented; Pi validation pending"),
)


def available_protocols() -> tuple[ProtocolInfo, ...]:
    return _PROTOCOLS


def get_protocol(name: str):
    for info in _PROTOCOLS:
        if info.name == name:
            return import_module(info.module).protocol
    raise KeyError(f"unknown protocol: {name}")
