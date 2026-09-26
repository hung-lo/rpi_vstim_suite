from __future__ import annotations

import socket
import time

from .publisher import UdpTelemetryPublisher


def run_benchmark(messages: int = 1000) -> dict[str, object]:
    """Measure parent-side publish latency using a local UDP receiver."""
    if messages < 1:
        raise ValueError("messages must be positive")
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    publisher = UdpTelemetryPublisher("127.0.0.1", receiver.getsockname()[1])
    samples_ns: list[int] = []
    try:
        for sequence in range(messages):
            started = time.perf_counter_ns()
            accepted = publisher.publish({"type": "state", "sequence_number": sequence})
            samples_ns.append(time.perf_counter_ns() - started)
            if not accepted:
                raise RuntimeError("local telemetry handoff dropped a benchmark packet")
    finally:
        publisher.close()
        receiver.close()
    samples_ns.sort()
    return {
        "messages": messages,
        "queued": publisher.queued_count,
        "sent": publisher.sent_count,
        "dropped": publisher.dropped_count,
        "errors": publisher.error_count,
        "p50_ms": _percentile_ms(samples_ns, 0.50),
        "p95_ms": _percentile_ms(samples_ns, 0.95),
        "p99_ms": _percentile_ms(samples_ns, 0.99),
        "max_ms": samples_ns[-1] / 1_000_000,
    }


def _percentile_ms(samples_ns: list[int], percentile: float) -> float:
    index = min(len(samples_ns) - 1, int((len(samples_ns) - 1) * percentile))
    return samples_ns[index] / 1_000_000
