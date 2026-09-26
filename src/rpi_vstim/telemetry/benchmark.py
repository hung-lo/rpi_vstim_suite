from __future__ import annotations

import socket
import threading
import time

from .publisher import UdpTelemetryPublisher


def run_benchmark(messages: int = 1000) -> dict[str, object]:
    """Measure parent-side publish latency using a local UDP receiver."""
    if messages < 1:
        raise ValueError("messages must be positive")
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(0.1)
    stop_reader = threading.Event()

    def drain_receiver() -> None:
        while not stop_reader.is_set():
            try:
                receiver.recv(65_535)
            except TimeoutError:
                continue
            except OSError:
                return

    reader = threading.Thread(target=drain_receiver, name="telemetry-benchmark-receiver")
    reader.start()
    publisher = UdpTelemetryPublisher("127.0.0.1", receiver.getsockname()[1])
    samples_ns: list[int] = []
    try:
        for sequence in range(messages):
            started = time.perf_counter_ns()
            publisher.publish({"type": "state", "sequence_number": sequence})
            samples_ns.append(time.perf_counter_ns() - started)
    finally:
        publisher.close()
        stop_reader.set()
        reader.join(timeout=1.0)
        receiver.close()
    samples_ns.sort()
    return {
        "messages": messages,
        "sampled": len(samples_ns),
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
