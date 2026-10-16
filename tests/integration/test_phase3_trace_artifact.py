import json
from pathlib import Path

import pytest

from rpi_vstim.display.timing import summarize_timestamps_ns


TRACE = (
    Path(__file__).parents[2]
    / "docs/hardware/pi5_phase3_combined_display_camera_2026-09-25.json"
)


def test_historical_phase3_trace_has_contiguous_callback_intervals():
    payload = json.loads(TRACE.read_text())
    events = payload["flip_events"]
    assert "kernel_event_ns" not in events[0]
    timestamps = tuple(event["monotonic_ns"] for event in events)
    summary = summarize_timestamps_ns(
        timestamps,
        nominal_refresh_hz=payload["nominal_refresh_hz"],
        tolerance_fraction=payload["interval_tolerance_fraction"],
        timestamp_source="legacy_callback_monotonic",
    )
    expected_us = 1_000_000.0 / payload["nominal_refresh_hz"]
    tolerance_us = expected_us * payload["interval_tolerance_fraction"]
    intervals = tuple(
        (right - left) / 1_000.0 for left, right in zip(timestamps, timestamps[1:])
    )
    long_indexes = tuple(
        index for index, value in enumerate(intervals) if value > expected_us + tolerance_us
    )
    short_indexes = tuple(
        index for index, value in enumerate(intervals) if value < expected_us - tolerance_us
    )

    assert summary.count == 3599
    assert summary.timestamp_source == "legacy_callback_monotonic"
    assert summary.outside_tolerance_count == payload["intervals_outside_tolerance"] == 210
    assert summary.long_interval_count == payload["long_interval_count"] == 105
    assert summary.short_interval_count == payload["short_interval_count"] == 105
    assert payload["missed_vblank_count"] == payload["estimated_dropped_frame_count"] == 0
    assert payload["restored"] is True
    assert all(
        events[index + 1]["frame_index"] == events[index]["frame_index"] + 1
        and events[index + 1]["kernel_sequence"] == events[index]["kernel_sequence"] + 1
        for index in range(len(events) - 1)
    )
    assert all(
        index + 1 < len(intervals) and intervals[index + 1] < expected_us
        for index in long_indexes
    )
    assert all(index > 0 and intervals[index - 1] > expected_us for index in short_indexes)
    assert all(
        abs(intervals[index] + intervals[index + 1] - 2 * expected_us) < 100.0
        for index in long_indexes
    )
    assert summary.estimated_refresh_hz == pytest.approx(payload["estimated_refresh_hz"], abs=0.001)
