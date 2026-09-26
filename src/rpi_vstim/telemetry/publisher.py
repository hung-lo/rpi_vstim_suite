from __future__ import annotations

import json
import socket
import threading
from collections import deque
from dataclasses import asdict, is_dataclass
from typing import Any


class TelemetryPublisher:
    """Phase 00 null publisher: no socket is opened and no packet is sent."""

    def __init__(self) -> None:
        self.suppressed_count = 0

    def publish(self, payload: object) -> bool:
        self.suppressed_count += 1
        return False

    def close(self) -> None:
        return None


class UdpTelemetryPublisher(TelemetryPublisher):
    """Best-effort UDP publisher with a nonblocking local datagram handoff."""

    _STOP = b"rpi-vstim-telemetry-stop"

    def __init__(
        self,
        host: str,
        port: int,
        *,
        max_packet_bytes: int = 4096,
        socket_buffer_bytes: int = 65_536,
    ) -> None:
        if not host:
            raise ValueError("telemetry host must not be empty")
        if not 1 <= port <= 65_535:
            raise ValueError("telemetry port must be between 1 and 65535")
        if max_packet_bytes < 1 or socket_buffer_bytes < 1:
            raise ValueError("telemetry socket bounds must be positive")
        if not hasattr(socket, "AF_UNIX"):
            raise RuntimeError("local datagram handoff requires AF_UNIX")
        self.host = host
        self.port = port
        self.max_packet_bytes = max_packet_bytes
        self.queued_count = 0
        self.sent_count = 0
        self.dropped_count = 0
        self.error_count = 0
        self._closed = False
        self._worker_failed = False
        self._lock = threading.Lock()
        self._handoff, worker_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._handoff.setblocking(False)
        try:
            self._handoff.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, socket_buffer_bytes)
        except OSError:
            # The kernel default is still bounded; some sandboxes reject this tuning call.
            pass
        worker_socket.settimeout(0.1)
        self._worker_socket = worker_socket
        self._worker = threading.Thread(
            target=self._run_worker,
            name="rpi-vstim-telemetry",
            daemon=True,
        )
        self._worker.start()

    @property
    def worker_alive(self) -> bool:
        return self._worker.is_alive()

    def publish(self, payload: object) -> bool:
        with self._lock:
            if self._closed or self._worker_failed or not self._worker.is_alive():
                return False
            try:
                packet = _json_packet(payload)
            except (TypeError, ValueError):
                self.error_count += 1
                return False
            if len(packet) > self.max_packet_bytes:
                self.dropped_count += 1
                return False
            try:
                self._handoff.send(packet)
            except (BlockingIOError, OSError):
                self.dropped_count += 1
                return False
            self.queued_count += 1
            return True

    def close(self, timeout_s: float = 1.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._handoff.send(self._STOP)
            except OSError:
                self.error_count += 1
        self._worker.join(timeout=max(timeout_s, 0.0))
        self._handoff.close()
        self._worker_socket.close()
        if self._worker.is_alive():
            self.error_count += 1

    def _run_worker(self) -> None:
        udp_socket: socket.socket | None = None
        try:
            addresses = socket.getaddrinfo(
                self.host,
                self.port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_DGRAM,
            )
            if not addresses:
                raise OSError("telemetry host did not resolve")
            family, _, _, _, destination = addresses[0]
            udp_socket = socket.socket(family, socket.SOCK_DGRAM)
            udp_socket.setblocking(False)
            while True:
                try:
                    packet = self._worker_socket.recv(self.max_packet_bytes + 1)
                except TimeoutError:
                    if self._closed:
                        break
                    continue
                except OSError:
                    break
                if packet == self._STOP:
                    break
                try:
                    udp_socket.sendto(packet, destination)
                except OSError:
                    self.error_count += 1
                    self._worker_failed = True
                else:
                    self.sent_count += 1
        except OSError:
            self.error_count += 1
            self._worker_failed = True
        finally:
            if udp_socket is not None:
                udp_socket.close()


class InMemoryTelemetryPublisher(TelemetryPublisher):
    """Bounded telemetry sink for simulated sessions and integration tests."""

    def __init__(
        self, *, fail: bool = False, fail_after: int | None = None, max_messages: int = 256
    ) -> None:
        self.fail = fail
        self.fail_after = fail_after
        self.publish_count = 0
        self.messages: deque[dict[str, Any]] = deque(maxlen=max_messages)
        self.dropped_count = 0
        self.failed = False

    def publish(self, payload: object) -> bool:
        if self.fail or (self.fail_after is not None and self.publish_count >= self.fail_after):
            self.failed = True
            return False
        self.publish_count += 1
        if len(self.messages) == self.messages.maxlen:
            self.dropped_count += 1
        if hasattr(payload, "as_dict"):
            payload = payload.as_dict()
        elif is_dataclass(payload):
            payload = asdict(payload)
        elif not isinstance(payload, dict):
            payload = {"payload": payload}
        self.messages.append(payload)
        return True


def _json_packet(payload: object) -> bytes:
    if hasattr(payload, "as_dict"):
        payload = payload.as_dict()
    elif is_dataclass(payload):
        payload = asdict(payload)
    elif not isinstance(payload, dict):
        payload = {"payload": payload}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
