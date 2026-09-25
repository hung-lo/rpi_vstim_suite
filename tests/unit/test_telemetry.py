import json

import pytest

from rpi_vstim.telemetry.payloads import TelemetryMessage
from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher, TelemetryPublisher


def test_telemetry_message_round_trips_with_optional_fields():
    message = TelemetryMessage(
        "trial",
        "session-1",
        "natural-images",
        "TASK",
        sequence_number=4,
        trial_id="7",
        stimulus="image-7",
        counters={"licks": 2, "rewards": 1},
        cameras=[{"camera_id": "face", "state": "RECORDING"}],
        degraded=["telemetry"],
    )

    restored = TelemetryMessage.from_json(message.to_json())
    assert restored == message
    assert json.loads(message.to_json())["schema_version"] == 3


def test_telemetry_message_rejects_wrong_version_or_missing_fields():
    with pytest.raises(ValueError, match="version"):
        TelemetryMessage.from_json('{"schema_version": 2}')
    with pytest.raises(ValueError, match="required"):
        TelemetryMessage.from_json('{"schema_version": 3}')


def test_in_memory_publisher_is_bounded_and_null_publisher_has_no_socket():
    publisher = InMemoryTelemetryPublisher(max_messages=2)
    for index in range(3):
        assert publisher.publish({"sequence_number": index})
    assert len(publisher.messages) == 2
    assert publisher.dropped_count == 1
    assert not TelemetryPublisher().publish({"ignored": True})
