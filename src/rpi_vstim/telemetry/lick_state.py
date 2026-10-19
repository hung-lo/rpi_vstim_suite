"""Bounded observer snapshots derived from the authoritative lick classifier."""

from __future__ import annotations

from collections import deque
from threading import Lock
import time
from typing import Any


class LickTelemetryState:
    def __init__(self, *, requested: bool, active_level: int) -> None:
        self.requested = requested
        self.active_level = active_level
        self._lock = Lock()
        self._available = False
        self._ever_available = False
        self._contact = {"left": None, "right": None}
        self._last_onset = {"left": None, "right": None}
        self._total = {"left": 0, "right": 0}
        self._recent = {"left": deque(maxlen=256), "right": deque(maxlen=256)}

    def set_available(self, available: bool) -> None:
        with self._lock:
            self._available = available
            self._ever_available = self._ever_available or available
            if not available:
                self._contact = {"left": None, "right": None}

    def record_edge(self, channel: str, level: int) -> None:
        name = _channel_name(channel)
        with self._lock:
            if self._available:
                self._contact[name] = level == self.active_level

    def record_onset(self, channel: str, timestamp_ns: int) -> None:
        name = _channel_name(channel)
        with self._lock:
            if self._available:
                self._last_onset[name] = timestamp_ns
                self._total[name] += 1
                self._recent[name].append(timestamp_ns)

    def snapshot(self, now_ns: int | None = None) -> dict[str, Any]:
        now_ns = time.monotonic_ns() if now_ns is None else now_ns
        with self._lock:
            channels = {}
            for name in ("left", "right"):
                recent = self._recent[name]
                while recent and recent[0] < now_ns - 2_000_000_000:
                    recent.popleft()
                last = self._last_onset[name]
                channels[name] = {
                    "available": self._available,
                    "status": "available" if self._available else (
                        "not_requested" if not self.requested else
                        "session_ended" if self._ever_available else "not_available"
                    ),
                    "contact_active": self._contact[name],
                    "last_lick_age_sec": None if last is None else max(0.0, (now_ns - last) / 1e9),
                    "recent_lick_count_2s": len(recent) if self._available or self._ever_available else None,
                    "total_lick_onset_count_session": (
                        self._total[name] if self._available or self._ever_available else None
                    ),
                }
            channels["center"] = {
                "available": False,
                "status": "not_configured",
                "contact_active": None,
                "last_lick_age_sec": None,
                "recent_lick_count_2s": None,
                "total_lick_onset_count_session": None,
            }
            if not self._available and not self._ever_available:
                return {
                    "requested": self.requested,
                    "channels": channels,
                    "licking_active": None,
                    "last_lick_age_sec": None,
                    "recent_lick_count_2s": None,
                    "total_lick_onset_count_session": None,
                }
            ages = [channel["last_lick_age_sec"] for channel in channels.values()
                    if channel["last_lick_age_sec"] is not None]
            return {
                "requested": self.requested,
                "channels": channels,
                "licking_active": any(self._contact.values()) if self._available else None,
                "last_lick_age_sec": min(ages) if ages else None,
                "recent_lick_count_2s": sum(
                    channels[name]["recent_lick_count_2s"] for name in ("left", "right")
                ),
                "total_lick_onset_count_session": sum(self._total.values()),
            }


def _channel_name(channel: str) -> str:
    if channel == "lick_left":
        return "left"
    if channel == "lick_right":
        return "right"
    raise ValueError(f"unsupported lick telemetry channel: {channel}")
