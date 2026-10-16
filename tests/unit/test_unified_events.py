import json

from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream


def test_reliable_burst_drains_without_queue_sized_storage(tmp_path):
    stream = UnifiedEventStream(
        tmp_path / "events.jsonl",
        session_id="burst",
        clock=SessionClock("burst", 10_000, 20_000),
        capacity=4096,
    )
    for index in range(20_000):
        stream.emit_reliable("BOUNDARY", frame=index)
    diagnostics = stream.close()
    assert diagnostics["event_enqueue_count"] == 20_000
    assert diagnostics["event_written_count"] == 20_000
    assert diagnostics["event_drop_count"] == 0
    assert diagnostics["event_queue_high_water_mark"] <= 4096
    assert sum(1 for _ in (json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines())) == 20_000
