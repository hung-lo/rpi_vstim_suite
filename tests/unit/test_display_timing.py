import pytest

from rpi_vstim.display.photodiode import PhotodiodePatch, patch_bounds, patch_value
from rpi_vstim.display.timing import summarize_intervals, summarize_timestamps_ns


def test_timing_summary_reports_percentiles_and_refresh():
    summary = summarize_intervals(
        (16_666.0, 16_667.0, 16_668.0, 17_500.0),
        nominal_refresh_hz=60.0,
    )
    assert summary.count == 4
    assert summary.median_us == 16_667.5
    assert summary.p95_us == 17_375.2
    assert summary.p99_us == 17_475.04
    assert summary.outside_tolerance_count == 0
    assert summary.estimated_refresh_hz == pytest.approx(59.25, abs=0.1)


def test_timestamps_and_invalid_intervals():
    summary = summarize_timestamps_ns(
        (1_000_000_000, 1_016_666_000, 1_033_332_000),
        nominal_refresh_hz=60.0,
    )
    assert summary.count == 2
    assert summary.median_us == 16_666.0
    with pytest.raises(ValueError, match="positive"):
        summarize_intervals((0.0,), nominal_refresh_hz=60.0)


def test_timing_summary_exposes_long_and_short_intervals():
    expected = 1_000_000.0 / 60.0
    summary = summarize_intervals(
        (expected, expected * 2, expected * 3, expected / 2),
        nominal_refresh_hz=60.0,
    )
    assert summary.long_interval_count == 2
    assert summary.short_interval_count == 1
    assert summary.estimated_dropped_frame_count == 3


def test_timestamps_reject_discontinuities():
    with pytest.raises(ValueError, match="positive"):
        summarize_timestamps_ns((100, 90), nominal_refresh_hz=60.0)


def test_photodiode_patch_is_configurable_and_deterministic():
    patch = PhotodiodePatch("top_left", 20, 200, 10)
    assert patch_bounds(100, 80, patch) == (0, 0, 20, 20)
    assert patch_value(patch, "on") == 200
    assert patch_value(patch, False) == 10
    with pytest.raises(ValueError, match="corner"):
        PhotodiodePatch("center", 20, 200, 10)
