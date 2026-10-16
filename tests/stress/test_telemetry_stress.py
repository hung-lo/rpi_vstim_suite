from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher


def test_telemetry_stays_bounded_under_burst():
    publisher = InMemoryTelemetryPublisher(max_messages=32)
    for index in range(1000):
        assert publisher.publish({"sequence": index})
    assert len(publisher.messages) == 32
    assert publisher.dropped_count == 968
    assert publisher.messages[-1]["sequence"] == 999
