from __future__ import annotations

import time


def monotonic_ns() -> int:
    return time.monotonic_ns()


def utc_ns() -> int:
    return time.time_ns()

