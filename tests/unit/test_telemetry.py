import json
import socket

import pytest

from rpi_vstim.telemetry.benchmark import run_benchmark
from rpi_vstim.telemetry.payloads import TelemetryMessage
from rpi_vstim.telemetry.publisher import (
    InMemoryTelemetryPublisher,
    TelemetryPublisher,
    UdpTelemetryPublisher,
)


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
    payload = json.loads(message.to_json())
    assert payload["schema_version"] == 1
    assert payload["telemetry_schema_version"] == 3
    assert payload["type"] == "trial_complete"


def test_grouped_operator_status_fields_round_trip():
    message = TelemetryMessage(
        "lifecycle", "s1", "natural-images", "READY",
        session={"id": "s1", "state": "READY"},
        hardware={"display": "ready"},
        integrity={"event_drops": 0},
        protocol_state={"phase": "prepared"},
        capabilities={"start": True, "stop": True, "abort": True},
        elapsed_s=0.0,
        control_schema_version=1,
    )
    assert TelemetryMessage.from_json(message.to_json()) == message


def test_telemetry_message_rejects_wrong_version_or_missing_fields():
    with pytest.raises(ValueError, match="version"):
        TelemetryMessage.from_json('{"schema_version": 2}')
    with pytest.raises(ValueError, match="version"):
        TelemetryMessage.from_json('{"schema_version": 3}')


def test_in_memory_publisher_is_bounded_and_null_publisher_has_no_socket():
    publisher = InMemoryTelemetryPublisher(max_messages=2)
    for index in range(3):
        assert publisher.publish({"sequence_number": index})
    assert len(publisher.messages) == 2
    assert publisher.dropped_count == 1
    assert not TelemetryPublisher().publish({"ignored": True})


def test_udp_publisher_delivers_json_via_local_loopback():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    publisher = UdpTelemetryPublisher("127.0.0.1", receiver.getsockname()[1])
    try:
        assert publisher.publish({"type": "state", "sequence_number": 7})
        publisher.close()
        payload, _ = receiver.recvfrom(4096)
        assert json.loads(payload) == {"sequence_number": 7, "type": "state"}
        assert publisher.queued_count == 1
        assert publisher.sent_count == 1
        assert not publisher.worker_alive
    finally:
        publisher.close()
        receiver.close()


def test_udp_publisher_rejects_oversized_packets_without_blocking():
    publisher = UdpTelemetryPublisher("127.0.0.1", 9, max_packet_bytes=8)
    try:
        assert not publisher.publish({"payload": "too large"})
        assert publisher.dropped_count == 1
    finally:
        publisher.close()


def test_udp_benchmark_uses_local_receiver():
    result = run_benchmark(messages=20)
    assert result["messages"] == 20
    assert result["sampled"] == 20
    assert result["queued"] == result["sent"] == 20
    assert result["dropped"] == result["errors"] == 0
