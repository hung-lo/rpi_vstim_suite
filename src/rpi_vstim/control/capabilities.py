"""Stable generic control capabilities advertised by the engine."""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_CAPABILITIES = {
    "start": True,
    "stop": True,
    "abort": True,
    "pause": False,
    "bait_left": False,
    "bait_right": False,
    "bait_center": False,
}


def normalize_capabilities(values: Mapping[str, bool] | None = None) -> dict[str, bool]:
    result = DEFAULT_CAPABILITIES.copy()
    if values is not None:
        for name, enabled in values.items():
            if not isinstance(name, str) or not name or type(enabled) is not bool:
                raise ValueError("capabilities must map non-empty names to booleans")
            if name not in DEFAULT_CAPABILITIES:
                raise ValueError(f"unsupported operator capability: {name}")
            if name == "pause" and enabled:
                raise ValueError("pause control is not implemented")
            result[name] = enabled
    return result
