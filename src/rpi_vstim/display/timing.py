"""Small, deterministic timing summaries for display validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from statistics import fmean, median, quantiles


@dataclass(frozen=True)
class TimingSummary:
    count: int
    median_us: float | None
    p95_us: float | None
    p99_us: float | None
    minimum_us: float | None
    maximum_us: float | None
    mean_us: float | None
    estimated_refresh_hz: float | None
    outside_tolerance_count: int
    long_interval_count: int = 0
    short_interval_count: int = 0
    estimated_dropped_frame_count: int = 0
    timestamp_source: str | None = None


def summarize_intervals(
    intervals_us: Sequence[float],
    *,
    nominal_refresh_hz: float,
    tolerance_fraction: float = 0.05,
) -> TimingSummary:
    if nominal_refresh_hz <= 0 or tolerance_fraction < 0:
        raise ValueError("nominal_refresh_hz must be positive and tolerance_fraction non-negative")
    values = tuple(float(value) for value in intervals_us)
    if any(value <= 0 for value in values):
        raise ValueError("frame intervals must be positive")
    if not values:
        return TimingSummary(0, None, None, None, None, None, None, None, 0)
    expected_us = 1_000_000.0 / nominal_refresh_hz
    outside = sum(
        abs(value - expected_us) > expected_us * tolerance_fraction for value in values
    )
    long_intervals = sum(
        value > expected_us * (1.0 + tolerance_fraction) for value in values
    )
    short_intervals = sum(
        value < expected_us * (1.0 - tolerance_fraction) for value in values
    )
    estimated_dropped = sum(
        max(0, round(value / expected_us) - 1)
        for value in values
        if value > expected_us * (1.0 + tolerance_fraction)
    )
    if len(values) == 1:
        p95 = p99 = values[0]
    else:
        quantile_values = quantiles(values, n=100, method="inclusive")
        p95, p99 = quantile_values[94], quantile_values[98]
    mean_us = fmean(values)
    return TimingSummary(
        len(values),
        median(values),
        p95,
        p99,
        min(values),
        max(values),
        mean_us,
        1_000_000.0 / mean_us,
        outside,
        long_intervals,
        short_intervals,
        estimated_dropped,
    )


def summarize_timestamps_ns(
    timestamps_ns: Sequence[int],
    *,
    nominal_refresh_hz: float,
    tolerance_fraction: float = 0.05,
    timestamp_source: str = "unknown",
) -> TimingSummary:
    values = tuple(int(value) for value in timestamps_ns)
    if any(value < 0 for value in values):
        raise ValueError("timestamps must be non-negative")
    intervals = tuple(
        (right - left) / 1_000.0 for left, right in pairwise(values)
    )
    return replace(
        summarize_intervals(
            intervals,
            nominal_refresh_hz=nominal_refresh_hz,
            tolerance_fraction=tolerance_fraction,
        ),
        timestamp_source=timestamp_source,
    )
