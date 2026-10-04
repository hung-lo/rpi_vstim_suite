"""Shared manual-bait service, keyboard path, and local IPC endpoint."""

from __future__ import annotations

import json
import os
import select
import socket
import stat
import sys
import termios
import threading
import time
import tty
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .lgpio_backend import LgpioBackend
from .operator_bait import (
    LgpioOperatorBaitMonitor,
    ManualBaitRequest,
    ManualBaitService,
)
from .reward import RewardArbiter, RewardBusyError, ensure_event_handoff
from .water import WaterAccounting

MAX_IPC_REQUEST_BYTES = 4096
MAX_PENDING_BAIT_REQUESTS = 8


class OperatorControlError(RuntimeError):
    """Raised when an operator-control service cannot start or accept a command."""


@dataclass(frozen=True)
class OperatorEnqueueResult:
    accepted: bool
    request_index: int | None = None
    reason: str = ""


class JsonlEventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: Any) -> None:
        payload = event.as_dict() if hasattr(event, "as_dict") else dict(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


class LocalOperatorControlEndpoint:
    """Restricted AF_UNIX command endpoint; it never opens GPIO itself."""

    def __init__(self, path: Path, enqueue: Callable[[str], object]):
        self.path = Path(path)
        self._enqueue = enqueue
        self._server: socket.socket | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.stat().st_mode):
                raise OperatorControlError(f"operator control path is not a socket: {self.path}")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.1)
                probe.connect(str(self.path))
            except OSError:
                self.path.unlink()
            else:
                raise OperatorControlError("an operator control service is already running")
            finally:
                probe.close()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            os.chmod(self.path, 0o600)
            server.listen(4)
            server.setblocking(False)
            self._server = server
        except BaseException:
            server.close()
            if self.path.exists() and stat.S_ISSOCK(self.path.stat().st_mode):
                self.path.unlink()
            raise

    def poll(self, timeout_s: float = 0.0) -> None:
        if self._server is None:
            return
        readable, _, _ = select.select([self._server], [], [], timeout_s)
        if not readable:
            return
        client, _ = self._server.accept()
        try:
            client.settimeout(0.25)
            payload = client.recv(MAX_IPC_REQUEST_BYTES + 1)
            if len(payload) > MAX_IPC_REQUEST_BYTES:
                self._reply(client, {"ok": False, "error": "request too large"})
                return
            request = json.loads(payload.decode("utf-8"))
            if request.get("command") not in {"bait", "manual_bait_request"}:
                raise OperatorControlError("unsupported operator command")
            result = self._enqueue("remote_cli")
            if isinstance(result, OperatorEnqueueResult):
                if not result.accepted:
                    self._reply(client, {"ok": False, "error": result.reason})
                    return
                index = result.request_index
            elif isinstance(result, int):
                index = result
            elif result is None:
                self._reply(client, {"ok": False, "error": "operator request queue is full"})
                return
            else:
                raise OperatorControlError("operator request was not accepted")
            self._reply(
                client,
                {"ok": True, "status": "accepted", "request_index": index, "source": "remote_cli"},
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, OperatorControlError) as exc:
            self._reply(client, {"ok": False, "error": str(exc)})
        finally:
            client.close()

    @staticmethod
    def _reply(client: socket.socket, payload: dict[str, object]) -> None:
        try:
            client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        except OSError:
            pass

    def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
        if self.path.exists() and stat.S_ISSOCK(self.path.stat().st_mode):
            self.path.unlink()

    def wake(self) -> None:
        """Wake a polling worker without creating an operator request."""
        if self._server is None:
            return
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(0.1)
            client.connect(str(self.path))
            client.sendall(b"{}")
        except OSError:
            pass
        finally:
            client.close()


def send_manual_bait(path: Path, *, timeout_s: float = 1.0) -> dict[str, object]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout_s)
        client.connect(str(path))
        client.sendall(b'{"command":"manual_bait_request"}\n')
        response = client.recv(MAX_IPC_REQUEST_BYTES)
    except OSError as exc:
        raise OperatorControlError(
            f"no compatible operator control service is running at {path}"
        ) from exc
    finally:
        client.close()
    return json.loads(response.decode("utf-8"))


class OperatorControlService:
    """One owner for GPIO19, GPIO23, bait accounting, keyboard, and IPC."""

    def __init__(
        self,
        config: Any,
        *,
        session_id: str = "operator-control",
        event_sink: Callable[[Any], None] | None = None,
        stdin: Any = sys.stdin,
        enable_keyboard: bool = True,
        backend: Any | None = None,
        monitor: Any | None = None,
        arbiter: RewardArbiter | None = None,
    ) -> None:
        if config.hardware.backend != "lgpio" and backend is None and arbiter is None:
            raise OperatorControlError("operator control requires the production lgpio backend")
        self.config = config
        self.session_id = session_id
        self._arbiter = arbiter
        sink = event_sink
        if sink is None and arbiter is not None:
            sink = arbiter.event_handoff
        if arbiter is not None and sink is None:
            raise OperatorControlError(
                "in-session operator control requires the session event handoff"
            )
        if sink is None:
            sink = JsonlEventLog(config.paths.operator_event_log)
        self._event_sink_source = sink
        self._event_handoff = ensure_event_handoff(sink)
        self._owns_event_handoff = self._event_handoff is not sink
        self._event_sink = self._event_handoff.publish if self._event_handoff is not None else None
        self._stdin = stdin
        self._enable_keyboard = enable_keyboard
        self._backend = backend
        self._monitor = monitor
        self._manual: ManualBaitService | None = None
        self._endpoint = LocalOperatorControlEndpoint(
            config.paths.operator_control_socket,
            self._enqueue_source,
        )
        self._pending: deque[ManualBaitRequest] = deque(maxlen=MAX_PENDING_BAIT_REQUESTS)
        self._pending_lock = threading.Lock()
        self._request_index = 0
        self._accepting_requests = True
        self._started = False
        self._last_request_ns: int | None = None
        self._keyboard_fd: int | None = None
        self._terminal_state: list[Any] | None = None
        self._stop_event = threading.Event()
        self._startup_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._worker_exited = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors: list[str] = []

    def _emit(self, event: Any) -> None:
        if self._event_sink is not None:
            self._event_sink(event)

    def _next_request_index(self) -> int:
        self._request_index += 1
        return self._request_index

    def _enqueue_source(self, source: str) -> OperatorEnqueueResult:
        if source not in {"terminal", "remote_cli"}:
            raise OperatorControlError(f"unsupported operator source: {source}")
        now_ns = time.monotonic_ns()
        if not self._accepting_requests:
            return OperatorEnqueueResult(False, reason="operator control is stopping")
        if not self.config.operator_controls.manual_bait_enabled:
            reason = "manual bait is disabled"
            self._emit({"event": "manual_bait_rejected", "source": source, "reason": reason,
                        "monotonic_ns": now_ns})
            return OperatorEnqueueResult(False, reason=reason)
        with self._pending_lock:
            minimum_ns = self.config.operator_controls.minimum_interval_ms * 1_000_000
            if (
                self._last_request_ns is not None
                and now_ns - self._last_request_ns < minimum_ns
            ):
                self._emit(
                    {
                        "event": "manual_bait_rejected",
                        "source": source,
                        "reason": "manual bait minimum interval has not elapsed",
                        "monotonic_ns": now_ns,
                    }
                )
                return OperatorEnqueueResult(
                    False, reason="manual bait minimum interval has not elapsed"
                )
            index = self._next_request_index()
            if len(self._pending) >= MAX_PENDING_BAIT_REQUESTS:
                return OperatorEnqueueResult(False, reason="operator request queue is full")
            self._last_request_ns = now_ns
            self._pending.append(ManualBaitRequest(None, now_ns, index, source))
            return OperatorEnqueueResult(True, request_index=index)

    def _on_button_request(self, request: ManualBaitRequest) -> None:
        if not self._accepting_requests:
            return
        if not self.config.operator_controls.manual_bait_enabled:
            self._emit({"event": "manual_bait_rejected", "source": "physical_button",
                        "reason": "manual bait is disabled", "gpio_bcm": request.bcm_pin,
                        "monotonic_ns": request.timestamp_ns})
            return
        with self._pending_lock:
            minimum_ns = self.config.operator_controls.minimum_interval_ms * 1_000_000
            if (
                self._last_request_ns is not None
                and request.timestamp_ns - self._last_request_ns < minimum_ns
            ):
                self._emit(
                    {
                        "event": "manual_bait_rejected",
                        "source": "physical_button",
                        "reason": "manual bait minimum interval has not elapsed",
                        "gpio_bcm": request.bcm_pin,
                        "monotonic_ns": request.timestamp_ns,
                    }
                )
                return
            if len(self._pending) >= MAX_PENDING_BAIT_REQUESTS:
                self._emit(
                    {
                        "event": "manual_bait_rejected",
                        "source": "physical_button",
                        "reason": "operator request queue is full",
                        "gpio_bcm": request.bcm_pin,
                        "monotonic_ns": request.timestamp_ns,
                    }
                )
                return
            self._last_request_ns = request.timestamp_ns
            self._pending.append(replace(request, request_index=self._next_request_index()))

    def _on_button_raw_edge(self, edge: Any) -> None:
        self._emit(
            {
                "event": "operator_bait_raw_edge",
                "gpio_bcm": edge.bcm_pin,
                "level": edge.level,
                "monotonic_ns": edge.timestamp_ns,
                "raw_edge_index": edge.raw_edge_index,
            }
        )

    def start(self) -> None:
        if self._started:
            return
        try:
            if self._event_handoff is None:
                self._event_handoff = ensure_event_handoff(self._event_sink_source)
                self._owns_event_handoff = self._event_handoff is not self._event_sink_source
                self._event_sink = (
                    self._event_handoff.publish if self._event_handoff is not None else None
                )
            if self._arbiter is not None:
                self._manual = ManualBaitService(
                    arbiter=self._arbiter,
                    session_id=self.session_id,
                    event_sink=self._event_sink,
                )
            else:
                if self._backend is None:
                    self._backend = LgpioBackend(
                        self.config.hardware,
                        roles=("reward_left",),
                        ownership_path=self.config.paths.reward_hardware_lock_path,
                    )
                self._backend.start()
                accounting = WaterAccounting(self.config.operator_controls.max_manual_bait_water_ul)
                self._manual = ManualBaitService.from_config(
                    self._backend,
                    self.config,
                    session_id=self.session_id,
                    event_sink=self._event_sink,
                    water_accounting=accounting,
                )
            if self.config.operator_controls.bait_button_enabled:
                if self._monitor is None:
                    self._monitor = LgpioOperatorBaitMonitor(
                        self.config,
                        on_raw_edge=self._on_button_raw_edge,
                        on_request=self._on_button_request,
                    )
                self._monitor.start()
            self._endpoint.start()
            self._start_keyboard()
            self._accepting_requests = True
            self._started = True
        except BaseException:
            try:
                self._teardown_resources()
            except BaseException as cleanup_error:  # noqa: BLE001 — preserve startup cause
                self.errors.append(f"startup cleanup: {cleanup_error}")
            raise

    def _start_keyboard(self) -> None:
        if not self._enable_keyboard or not getattr(self._stdin, "isatty", lambda: False)():
            return
        self._keyboard_fd = self._stdin.fileno()
        self._terminal_state = termios.tcgetattr(self._keyboard_fd)
        tty.setcbreak(self._keyboard_fd)

    def _poll_keyboard(self) -> None:
        if self._keyboard_fd is None:
            return
        readable, _, _ = select.select([self._keyboard_fd], [], [], 0)
        if readable:
            self.submit_terminal_key(self._stdin.read(1))

    def submit_terminal_key(self, key: str) -> bool:
        """Handle one nonblocking terminal key without bypassing the queue."""
        return key.lower() == "b" and self._enqueue_source("terminal").accepted

    def _drain_one(self) -> None:
        if self._manual is None:
            return
        with self._pending_lock:
            if not self._pending:
                return
            request = self._pending.popleft()
        if request.source == "physical_button":
            self._emit(
                {
                    "event": "operator_bait_button_press",
                    "gpio_bcm": request.bcm_pin,
                    "monotonic_ns": request.timestamp_ns,
                    "session_id": self.session_id,
                }
            )
        try:
            self._manual.handle_request(request)
        except RewardBusyError as exc:
            self.errors.append(str(exc))
            self._emit(
                {
                    "event": "manual_bait_rejected",
                    "source": request.source,
                    "reason": str(exc),
                    "monotonic_ns": time.monotonic_ns(),
                }
            )
        except Exception as exc:  # noqa: BLE001 — keep the service alive after one request
            self.errors.append(str(exc))
            self._emit(
                {
                    "event": "manual_bait_error",
                    "source": request.source,
                    "reason": str(exc),
                    "monotonic_ns": time.monotonic_ns(),
                }
            )

    def run_forever(self, *, stop: Callable[[], bool] | None = None) -> None:
        try:
            self.start()
            self._run_loop(stop=stop)
        finally:
            self.stop()

    def _run_loop(self, *, stop: Callable[[], bool] | None = None) -> None:
        while not self._stop_event.is_set() and (stop is None or not stop()):
            self._endpoint.poll(0.02)
            self._poll_keyboard()
            self._drain_one()

    def _background_main(self) -> None:
        try:
            self.start()
            self._startup_event.set()
            self._run_loop()
        except BaseException as exc:  # noqa: BLE001 — propagate startup and worker failures
            self._startup_error = exc
            self.errors.append(str(exc))
            self._startup_event.set()
        finally:
            self._worker_exited.set()

    def start_background(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._startup_event.clear()
        self._worker_exited.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._background_main,
            name="rpi-vstim-operator",
            daemon=True,
        )
        self._thread.start()
        if not self._startup_event.wait(2.0):
            self.stop()
            raise OperatorControlError("operator control startup acknowledgement timed out")
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise OperatorControlError(f"operator control failed to start: {error}") from error

    def stop(self) -> None:
        self._accepting_requests = False
        self._stop_event.set()
        self._endpoint.wake()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive() or not self._worker_exited.is_set():
                self._force_inactive()
                raise OperatorControlError("operator control worker did not stop cleanly")
            self._thread = None
        self._teardown_resources()

    def _force_inactive(self) -> None:
        try:
            if self._arbiter is not None:
                self._arbiter.controller._deactivate()
            elif self._backend is not None:
                line = self.config.hardware.output_line("reward_left")
                self._backend.set_level("reward_left", line.initial_level)
        except BaseException as exc:  # noqa: BLE001 — report, never mask stop failure
            self.errors.append(f"operator force-inactive failed: {exc}")

    def _teardown_resources(self) -> None:
        errors: list[BaseException] = []
        if self._keyboard_fd is not None and self._terminal_state is not None:
            try:
                termios.tcsetattr(self._keyboard_fd, termios.TCSADRAIN, self._terminal_state)
            except BaseException as exc:  # noqa: BLE001 — continue cleanup
                errors.append(exc)
        self._keyboard_fd = None
        self._terminal_state = None
        try:
            if self._monitor is not None:
                self._monitor.stop()
        except BaseException as exc:  # noqa: BLE001 — continue cleanup
            errors.append(exc)
        self._monitor = None
        try:
            self._endpoint.close()
        except BaseException as exc:  # noqa: BLE001 — continue cleanup
            errors.append(exc)
        try:
            if self._manual is not None:
                self._manual.close()
        except BaseException as exc:  # noqa: BLE001 — continue cleanup
            errors.append(exc)
        self._manual = None
        try:
            if self._backend is not None:
                self._backend.stop()
        except BaseException as exc:  # noqa: BLE001 — continue cleanup
            errors.append(exc)
        self._backend = None
        self._started = False
        if self._owns_event_handoff and self._event_handoff is not None:
            try:
                self._event_handoff.close()
            except BaseException as exc:  # noqa: BLE001 — continue cleanup
                errors.append(exc)
            else:
                self._event_handoff = None
                self._event_sink = None
        if errors:
            raise OperatorControlError("operator control cleanup failed: " + "; ".join(map(str, errors)))
