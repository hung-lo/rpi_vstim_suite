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
        stimulus_state={
            "phase": "TASK", "stimulus_kind": "natural_image",
            "image_id": "natimg_center_0007", "image_index": 7,
            "image_filename": "natimg_center_0007.png", "sequence_index": 4,
        },
        lick_state={
            "requested": True, "licking_active": False, "last_lick_age_sec": 0.2,
            "recent_lick_count_2s": 2, "total_lick_onset_count_session": 5,
            "channels": {"left": {"available": True}, "right": {"available": True}},
        },
    )

    restored = TelemetryMessage.from_json(message.to_json())
    assert restored == message
    payload = json.loads(message.to_json())
    assert payload["schema_version"] == 1
    assert payload["telemetry_schema_version"] == 3
    assert payload["type"] == "trial_complete"
    assert payload["stimulus_state"]["image_index"] == 7
    assert payload["licking_active"] is False
    assert payload["total_lick_onset_count_session"] == 5


def test_lick_state_is_independent_bounded_and_recovers_after_lost_snapshot():
    from rpi_vstim.telemetry.lick_state import LickTelemetryState

    state = LickTelemetryState(requested=True, active_level=1)
    state.set_available(True)
    state.record_edge("lick_left", 1)
    assert state.snapshot(now_ns=2_000_000_000)["channels"]["left"]["contact_active"] is True
    assert state.snapshot(now_ns=2_000_000_000)["channels"]["left"]["total_lick_onset_count_session"] == 0
    state.record_onset("lick_left", 2_000_000_000)
    state.record_edge("lick_right", 1)
    state.record_onset("lick_right", 2_100_000_000)
    state.record_edge("lick_left", 0)

    recovered = state.snapshot(now_ns=2_200_000_000)
    assert recovered["channels"]["left"]["contact_active"] is False
    assert recovered["channels"]["right"]["contact_active"] is True
    assert recovered["channels"]["left"]["total_lick_onset_count_session"] == 1
    assert recovered["channels"]["right"]["total_lick_onset_count_session"] == 1
    assert recovered["recent_lick_count_2s"] == 2
    assert recovered["total_lick_onset_count_session"] == 2
    assert recovered["channels"]["center"]["status"] == "not_configured"

    expired = state.snapshot(now_ns=4_200_000_001)
    assert expired["recent_lick_count_2s"] == 0
    assert expired["total_lick_onset_count_session"] == 2


def test_missing_lick_flag_and_session_reset_are_not_reported_as_zero_monitoring():
    from rpi_vstim.telemetry.lick_state import LickTelemetryState

    missing = LickTelemetryState(requested=False, active_level=1).snapshot()
    assert missing["channels"]["left"]["status"] == "not_requested"
    assert missing["channels"]["left"]["recent_lick_count_2s"] is None
    assert missing["channels"]["center"]["available"] is False

    first = LickTelemetryState(requested=True, active_level=1)
    first.set_available(True)
    first.record_onset("lick_right", 10)
    second = LickTelemetryState(requested=True, active_level=1)
    second.set_available(True)
    assert second.snapshot(now_ns=10)["total_lick_onset_count_session"] == 0
    first.set_available(False)
    assert first.snapshot(now_ns=10)["channels"]["right"]["status"] == "session_ended"


def test_optional_identity_telemetry_fits_existing_udp_bound():
    from rpi_vstim.telemetry.publisher import _json_packet

    payload = TelemetryMessage(
        "lifecycle", "s1", "natural-images", "RUNNING",
        stimulus_state={"phase": "TASK", "stimulus_kind": "natural_image",
                        "image_id": "natimg_center_2799", "image_index": 2799,
                        "image_filename": "natimg_center_2799.png", "sequence_index": 20},
        lick_state={
            "requested": True, "licking_active": True, "last_lick_age_sec": 0.01,
            "recent_lick_count_2s": 3, "total_lick_onset_count_session": 100,
            "channels": {name: {"available": True, "status": "available",
                                  "contact_active": True, "last_lick_age_sec": 0.01,
                                  "recent_lick_count_2s": 2,
                                  "total_lick_onset_count_session": 50}
                         for name in ("left", "right", "center")},
        },
    )
    assert len(_json_packet(payload)) < 4096


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
