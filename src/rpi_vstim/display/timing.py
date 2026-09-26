"""Small, deterministic timing summaries for display validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from statistics import fmean, median, quantiles
from typing import Any


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


@dataclass(frozen=True)
class FlipTraceAnalysis:
    kernel_summary: TimingSummary | None
    callback_summary: TimingSummary | None
    kernel_sequence_gap_count: int
    frame_index_gap_count: int
    frame_metadata_mismatch_count: int
    paired_callback_displacement_count: int
    callback_dispatch_latency_ns: tuple[int, ...]


def comparable_callback_timestamp_ns(
    kernel_timestamp_clock: str,
    *,
    callback_monotonic_ns: int | None,
    callback_realtime_ns: int | None,
) -> int | None:
    """Select only the callback clock comparable to the kernel event clock."""
    if kernel_timestamp_clock == "monotonic":
        return callback_monotonic_ns
    if kernel_timestamp_clock == "realtime":
        return callback_realtime_ns
    if kernel_timestamp_clock == "unknown":
        return None
    raise ValueError(f"unsupported kernel timestamp clock: {kernel_timestamp_clock}")


def analyze_flip_events(
    events: Sequence[dict[str, Any]],
    *,
    nominal_refresh_hz: float,
    tolerance_fraction: float = 0.05,
    kernel_timestamp_clock: str = "unknown",
) -> FlipTraceAnalysis:
    """Analyze corrected native events without rewriting or mutating a trace."""
    if not events:
        return FlipTraceAnalysis(None, None, 0, 0, 0, 0, ())
    kernel_values = tuple(int(event["kernel_event_ns"]) for event in events)
    callback_values = tuple(int(event["callback_monotonic_ns"]) for event in events)
    kernel_summary = (
        summarize_timestamps_ns(
            kernel_values,
            nominal_refresh_hz=nominal_refresh_hz,
            tolerance_fraction=tolerance_fraction,
            timestamp_source="kernel_event",
        )
        if all(value > 0 for value in kernel_values)
        else None
    )
    callback_summary = summarize_timestamps_ns(
        callback_values,
        nominal_refresh_hz=nominal_refresh_hz,
        tolerance_fraction=tolerance_fraction,
        timestamp_source="callback_monotonic",
    )
    sequence_gaps = sum(
        right["kernel_sequence"] != left["kernel_sequence"] + 1
        for left, right in pairwise(events)
    )
    frame_gaps = sum(
        right["frame_index"] != left["frame_index"] + 1
        for left, right in pairwise(events)
    )
    metadata_mismatches = sum(
        event["buffer_index"] != event["frame_index"] % 2
        or event["photodiode_state"] != ("on" if event["frame_index"] % 2 == 0 else "off")
        for event in events
    )
    expected = 1_000_000.0 / nominal_refresh_hz
    callback_intervals = tuple(
        (right - left) / 1_000.0 for left, right in pairwise(callback_values)
    )
    paired = sum(
        current > expected * (1.0 + tolerance_fraction)
        and following < expected * (1.0 - tolerance_fraction)
        for current, following in pairwise(callback_intervals)
    )
    latency: list[int] = []
    for event in events:
        callback = comparable_callback_timestamp_ns(
            kernel_timestamp_clock,
            callback_monotonic_ns=int(event["callback_monotonic_ns"]),
            callback_realtime_ns=(
                int(event["callback_realtime_ns"])
                if event.get("callback_realtime_ns") is not None
                else None
            ),
        )
        if callback is not None and int(event["kernel_event_ns"]) > 0:
            latency.append(callback - int(event["kernel_event_ns"]))
    return FlipTraceAnalysis(
        kernel_summary,
        callback_summary,
        sequence_gaps,
        frame_gaps,
        metadata_mismatches,
        paired,
        tuple(latency),
    )


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
