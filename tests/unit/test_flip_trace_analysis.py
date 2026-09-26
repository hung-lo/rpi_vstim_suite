from rpi_vstim.display.timing import analyze_flip_events


def events(count=4):
    return [
        {
            "frame_index": index,
            "buffer_index": index % 2,
            "photodiode_state": "on" if index % 2 == 0 else "off",
            "kernel_sequence": 100 + index,
            "kernel_event_ns": 1_000_000_000 + index * 16_666_000,
            "callback_monotonic_ns": 1_000_000_100 + index * 16_666_000,
            "callback_realtime_ns": 2_000_000_000 + index * 16_666_000,
        }
        for index in range(count)
    ]


def test_flip_analysis_separates_kernel_callback_and_comparable_latency():
    analysis = analyze_flip_events(
        events(),
        nominal_refresh_hz=60.0,
        kernel_timestamp_clock="monotonic",
    )
    assert analysis.kernel_summary.timestamp_source == "kernel_event"
    assert analysis.callback_summary.timestamp_source == "callback_monotonic"
    assert analysis.callback_dispatch_latency_ns == (100, 100, 100, 100)
    assert analysis.kernel_sequence_gap_count == 0
    assert analysis.frame_index_gap_count == 0
    assert analysis.frame_metadata_mismatch_count == 0


def test_flip_analysis_does_not_report_unknown_clock_latency():
    trace = events()
    trace[2]["kernel_sequence"] = 999
    trace[2]["buffer_index"] = 1
    analysis = analyze_flip_events(
        trace,
        nominal_refresh_hz=60.0,
        kernel_timestamp_clock="unknown",
    )
    assert analysis.callback_dispatch_latency_ns == ()
    assert analysis.kernel_sequence_gap_count == 2
    assert analysis.frame_metadata_mismatch_count == 1


def test_flip_analysis_marks_callback_long_short_pair_separately():
    trace = events(4)
    trace[2]["callback_monotonic_ns"] = trace[1]["callback_monotonic_ns"] + 25_000_000
    trace[3]["callback_monotonic_ns"] = trace[2]["callback_monotonic_ns"] + 8_000_000
    analysis = analyze_flip_events(trace, nominal_refresh_hz=60.0)
    assert analysis.paired_callback_displacement_count == 1
