import pytest

from rpi_vstim.display.sequence import FrameTransportAborted, FrameTransportBackpressure
from rpi_vstim.display.transport import (
    DisplaySequenceFrame,
    DisplaySequenceMetadata,
    InMemoryDisplaySequenceAdapter,
)


def frame(index: int, payload: bytes = b"pixels") -> DisplaySequenceFrame:
    return DisplaySequenceFrame(
        DisplaySequenceMetadata(index, "event", "sequence", "asset", "on", len(payload), index),
        payload,
    )


def test_display_adapter_preserves_payload_identity_and_requires_ack():
    adapter = InMemoryDisplaySequenceAdapter(2)
    payload = b"shared-payload"
    adapter.publish(frame(0, payload))
    lease = adapter.consume(timeout_s=0)
    assert lease is not None
    assert lease.frame.payload is payload
    assert adapter.metrics()["inflight"] == 1
    adapter.publish(frame(1, b"one"), timeout_s=0)
    with pytest.raises(FrameTransportBackpressure):
        adapter.publish(frame(2, b"two"), timeout_s=0)
    lease.acknowledge()
    adapter.publish(frame(2, b"two"), timeout_s=0)
    adapter.finish()
    assert adapter.consume(timeout_s=0) is not None


def test_display_adapter_abort_is_fail_fast_and_bounded():
    adapter = InMemoryDisplaySequenceAdapter(2)
    adapter.publish(frame(0))
    adapter.abort("display consumer failed")
    with pytest.raises(FrameTransportAborted, match="display consumer failed"):
        adapter.consume(timeout_s=0)
    with pytest.raises(FrameTransportAborted, match="display consumer failed"):
        adapter.publish(frame(1), timeout_s=0)
