"""Reliable, protocol-neutral command handling for one experiment process."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .capabilities import normalize_capabilities
from .lifecycle import ExperimentLifecycle, ExperimentState
from .state_file import ControlStateFile

CONTROL_SCHEMA_VERSION = 1
_REQUEST_CACHE_SIZE = 128
_SEMANTIC_CHANNELS = {"left", "right", "center"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ExperimentControl:
    """Own lifecycle state, deduplicated commands, and protocol worker lifetime."""

    def __init__(
        self,
        *,
        session_id: str,
        protocol: str,
        run: Callable[[ExperimentControl], Any],
        capabilities: Mapping[str, bool] | None = None,
        planned_duration_s: float | None = None,
        semantic_actions: Mapping[str, Callable[[str, str], Any]] | None = None,
        control_state_file: Path | None = None,
    ) -> None:
        if not session_id or not protocol:
            raise ValueError("session_id and protocol are required")
        if planned_duration_s is not None and planned_duration_s < 0:
            raise ValueError("planned duration must be non-negative")
        self.session_id = session_id
        self.protocol = protocol
        self.capabilities = normalize_capabilities(capabilities)
        self.planned_duration_s = planned_duration_s
        self._run = run
        self._semantic_actions = dict(semantic_actions or {})
        self._lifecycle = ExperimentLifecycle()
        self._lock = threading.RLock()
        self.control_instance_id = uuid.uuid4().hex
        self.process_id = os.getpid()
        self._state_file = ControlStateFile(control_state_file) if control_state_file is not None else None
        self._state_reason: str | None = None
        self._session_output_path: str | None = None
        self._finished = threading.Event()
        self._stop = threading.Event()
        self._abort = threading.Event()
        self._worker: threading.Thread | None = None
        self._result: Any = None
        self._started_monotonic_ns: int | None = None
        self._terminal_monotonic_ns: int | None = None
        self._event_sink: Callable[[dict[str, Any]], None] | None = None
        self._pending_events: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._request_cache: OrderedDict[str, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()
        self._start_metadata: dict[str, Any] | None = None
        self._stop_metadata: dict[str, Any] | None = None
        self._abort_metadata: dict[str, Any] | None = None
        self._error: str | None = None
        self._hardware: dict[str, Any] = {}
        self._integrity: dict[str, Any] = {}
        self._protocol_state: dict[str, Any] = {}
        self.prepared_monotonic_ns = time.monotonic_ns()
        self.prepared_utc = _utc_now()
        self.ready_monotonic_ns: int | None = None
        self.ready_utc: str | None = None
        self._state_updated_monotonic_ns = self.prepared_monotonic_ns
        self._state_updated_utc = self.prepared_utc
        self._terminal_utc: str | None = None
        self._record("CONTROL_PREPARING", source="engine")
        self._persist_state(ExperimentState.PREPARING)

    @property
    def state(self) -> ExperimentState:
        with self._lock:
            return self._lifecycle.state

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    @property
    def abort_requested(self) -> bool:
        return self._abort.is_set()

    @property
    def finished(self) -> threading.Event:
        return self._finished

    @property
    def result(self) -> Any:
        return self._result

    def mark_ready(self) -> None:
        with self._lock:
            self.ready_monotonic_ns = time.monotonic_ns()
            self.ready_utc = _utc_now()
            try:
                self._transition(ExperimentState.READY)
            except Exception:
                self.ready_monotonic_ns = None
                self.ready_utc = None
                raise
            self._record("CONTROL_READY", source="engine")

    def mark_finishing(self) -> None:
        with self._lock:
            if self._lifecycle.state == ExperimentState.RUNNING:
                self._transition(ExperimentState.FINISHING)

    def update_snapshot(
        self,
        *,
        hardware: Mapping[str, Any] | None = None,
        integrity: Mapping[str, Any] | None = None,
        protocol_state: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if hardware is not None:
                self._hardware.update(hardware)
            if integrity is not None:
                self._integrity.update(integrity)
            if protocol_state is not None:
                self._protocol_state.update(protocol_state)

    def fail_preparation(self, error: str) -> None:
        with self._lock:
            if self._lifecycle.state in {ExperimentState.PREPARING, ExperimentState.READY}:
                self._error = error
                self._transition(ExperimentState.ERROR, reason="preparation_error")
                self._record("CONTROL_ERROR", source="engine", error=error)
                self._finished.set()

    def _state_document(
        self,
        state: ExperimentState,
        *,
        updated_monotonic_ns: int,
        updated_utc: str,
        terminal_monotonic_ns: int | None = None,
        terminal_utc: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        terminal = state in {ExperimentState.COMPLETE, ExperimentState.ERROR, ExperimentState.ABORTED}
        triggering = self._abort_metadata or self._stop_metadata
        command = "abort" if self._abort_metadata is not None else "stop" if self._stop_metadata else None
        error_summary = self._error.splitlines()[0][:512] if self._error else None
        return {
            "artifact_type": "rpi_vstim.operator_control_state",
            "schema_version": 1,
            "session_id": self.session_id,
            "protocol": self.protocol,
            "state": state.value,
            "lifecycle": state.value,
            "terminal": terminal,
            "control_instance_id": self.control_instance_id,
            "process_id": self.process_id,
            "prepared_at_utc": self.prepared_utc,
            "prepared_monotonic_ns": self.prepared_monotonic_ns,
            "ready_at_utc": self.ready_utc,
            "ready_monotonic_ns": self.ready_monotonic_ns,
            "start": self._start_metadata,
            "stop": self._stop_metadata,
            "abort": self._abort_metadata,
            "terminal_command": command if terminal else None,
            "terminal_request_id": triggering.get("request_id") if terminal and triggering else None,
            "updated_at_utc": updated_utc,
            "updated_monotonic_ns": updated_monotonic_ns,
            "terminal_at_utc": terminal_utc if terminal else None,
            "terminal_monotonic_ns": terminal_monotonic_ns if terminal else None,
            "reason": reason if terminal else None,
            "error_summary": error_summary if state == ExperimentState.ERROR else None,
            "session_output_path": self._session_output_path,
        }

    def _persist_state(
        self,
        state: ExperimentState,
        *,
        updated_monotonic_ns: int | None = None,
        updated_utc: str | None = None,
        terminal_monotonic_ns: int | None = None,
        terminal_utc: str | None = None,
        reason: str | None = None,
    ) -> None:
        if self._state_file is None:
            return
        updated_monotonic_ns = updated_monotonic_ns or time.monotonic_ns()
        updated_utc = updated_utc or _utc_now()
        if state in {ExperimentState.COMPLETE, ExperimentState.ERROR, ExperimentState.ABORTED}:
            terminal_monotonic_ns = terminal_monotonic_ns or updated_monotonic_ns
            terminal_utc = terminal_utc or updated_utc
        self._state_file.write(self._state_document(
            state,
            updated_monotonic_ns=updated_monotonic_ns,
            updated_utc=updated_utc,
            terminal_monotonic_ns=terminal_monotonic_ns,
            terminal_utc=terminal_utc,
            reason=reason if reason is not None else self._state_reason,
        ))

    def _transition(self, state: ExperimentState, *, reason: str | None = None) -> None:
        self._lifecycle.validate_transition(state)
        now_ns, now_utc = time.monotonic_ns(), _utc_now()
        terminal = state in {ExperimentState.COMPLETE, ExperimentState.ERROR, ExperimentState.ABORTED}
        self._persist_state(
            state,
            updated_monotonic_ns=now_ns,
            updated_utc=now_utc,
            terminal_monotonic_ns=now_ns if terminal else None,
            terminal_utc=now_utc if terminal else None,
            reason=reason if terminal else None,
        )
        self._lifecycle.transition(state)
        self._state_updated_monotonic_ns = now_ns
        self._state_updated_utc = now_utc
        if terminal:
            self._terminal_monotonic_ns = now_ns
            self._terminal_utc = now_utc
            self._state_reason = reason

    def _record(self, event: str, **fields: Any) -> None:
        item = {
            "event": event,
            "source": "operator" if fields.get("command") else "engine",
            "monotonic_ns": time.monotonic_ns(),
            "utc_time": _utc_now(),
            **fields,
        }
        self._history.append(item)
        if event == "OPERATOR_COMMAND" or event == "OPERATOR_ACTION":
            if self._event_sink is None:
                self._pending_events.append(item)
            else:
                self._event_sink(item)

    def bind_event_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._event_sink = sink
            pending, self._pending_events = self._pending_events, []
            for item in pending:
                sink(item)

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._lifecycle.state.value
            elapsed = (
                max(0.0, (time.monotonic_ns() - self._started_monotonic_ns) / 1e9)
                if self._started_monotonic_ns is not None
                else 0.0
            )
            if self._started_monotonic_ns is not None and self._terminal_monotonic_ns is not None:
                elapsed = max(
                    0.0,
                    (self._terminal_monotonic_ns - self._started_monotonic_ns) / 1e9,
                )
            eta = (
                max(0.0, self.planned_duration_s - elapsed)
                if state in {"RUNNING", "FINISHING"} and self.planned_duration_s is not None
                else None
            )
            session = {
                "id": self.session_id,
                "protocol": self.protocol,
                "state": state,
                "lifecycle": state,
                "elapsed_s": elapsed,
                "eta_s": eta,
            }
            capabilities = self.capabilities.copy()
            capabilities["start"] = capabilities.get("start", False) and state == "READY"
            capabilities["stop"] = capabilities.get("stop", False) and state == "RUNNING"
            capabilities["abort"] = capabilities.get("abort", False) and state in {
                "PREPARING", "READY", "RUNNING"
            }
            for name in ("bait_left", "bait_right", "bait_center"):
                capabilities[name] = capabilities.get(name, False) and state in {"READY", "RUNNING"}
            return {
                "control_schema_version": CONTROL_SCHEMA_VERSION,
                "control_instance_id": self.control_instance_id,
                "session_id": self.session_id,
                "protocol": self.protocol,
                "state": state,
                "lifecycle": state,
                "elapsed_s": elapsed,
                "eta_s": eta,
                "session": session,
                "hardware": self._hardware.copy(),
                "integrity": self._integrity.copy(),
                "protocol_state": self._protocol_state.copy(),
                "capabilities": capabilities,
                "error": self._error,
            }

    def provenance(self) -> dict[str, Any]:
        with self._lock:
            return {
                "control_mode": "supervisor/operator",
                "control_schema_version": CONTROL_SCHEMA_VERSION,
                "prepare_monotonic_ns": self.prepared_monotonic_ns,
                "prepare_utc": self.prepared_utc,
                "ready_monotonic_ns": self.ready_monotonic_ns,
                "ready_utc": self.ready_utc,
                "start": self._start_metadata,
                "stop": self._stop_metadata,
                "abort": self._abort_metadata,
                "state": self._lifecycle.state.value,
                "history": list(self._history),
            }

    def handle_request(self, request: object) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._error_response(None, "invalid_request", "request must be a JSON object")
        request_id = request.get("request_id")
        schema_version = request.get("schema_version", CONTROL_SCHEMA_VERSION)
        if type(schema_version) is not int or schema_version != CONTROL_SCHEMA_VERSION:
            return self._error_response(request_id if isinstance(request_id, str) else None,
                                        "unsupported_schema", "schema_version must be 1")
        command = request.get("command")
        if command == "status":
            if set(request) - {"schema_version", "request_id", "command"}:
                return self._error_response(request_id if isinstance(request_id, str) else None,
                                            "invalid_request", "status has unexpected fields")
            return self._success_response(request_id if isinstance(request_id, str) else None)
        if not isinstance(command, str):
            return self._error_response(None, "invalid_request", "command is required")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            return self._error_response(None, "invalid_request", "mutating commands require a request_id")
        signature = {key: value for key, value in request.items() if key != "request_id"}
        signature.setdefault("schema_version", CONTROL_SCHEMA_VERSION)
        with self._lock:
            cached = self._request_cache.get(request_id)
            if cached is not None:
                self._request_cache.move_to_end(request_id)
                if cached[0] == signature:
                    return cached[1].copy()
                return self._error_response(request_id, "request_id_conflict",
                                            "request_id was already used for a different command")
            try:
                response = self._dispatch(command, request_id, request)
            except Exception as exc:  # noqa: BLE001 - a command must not kill the control server.
                response = self._error_response(request_id, "command_failed", str(exc))
            self._request_cache[request_id] = (signature, response.copy())
            while len(self._request_cache) > _REQUEST_CACHE_SIZE:
                self._request_cache.popitem(last=False)
            return response

    def _dispatch(self, command: str, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        expected = {"request_id", "command"}
        if "schema_version" in request:
            expected.add("schema_version")
        if command == "deliver_bait":
            expected.add("channel")
        if set(request) != expected:
            return self._error_response(request_id, "invalid_request", f"unexpected fields for {command}")
        now_ns, now_utc_ns = time.monotonic_ns(), time.time_ns()
        now_utc = datetime.fromtimestamp(now_utc_ns / 1e9, UTC).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        state = self._lifecycle.state
        if command == "start":
            if state != ExperimentState.READY or not self.capabilities.get("start", False):
                return self._error_response(request_id, "invalid_state", "start is allowed only from READY")
            self._started_monotonic_ns = now_ns
            self._start_metadata = {"request_id": request_id, "request_monotonic_ns": now_ns,
                                    "request_utc": now_utc, "request_utc_ns": now_utc_ns,
                                    "accepted_monotonic_ns": now_ns, "accepted_utc": now_utc,
                                    "accepted_utc_ns": now_utc_ns}
            try:
                self._transition(ExperimentState.RUNNING)
            except Exception:
                self._started_monotonic_ns = None
                self._start_metadata = None
                raise
            self._record("OPERATOR_COMMAND", command="start", request_id=request_id,
                         request_monotonic_ns=now_ns, request_utc=now_utc,
                         request_utc_ns=now_utc_ns, result="accepted")
            self._worker = threading.Thread(target=self._run_worker, name="rpi-vstim-protocol", daemon=True)
            try:
                self._worker.start()
            except Exception as exc:  # noqa: BLE001 - worker startup must report its failure.
                self._error = str(exc)
                try:
                    self._transition(ExperimentState.ERROR, reason="worker_start_error")
                finally:
                    self._finished.set()
                return self._error_response(request_id, "worker_start_failed", str(exc))
            return self._success_response(request_id)
        if command == "stop":
            if state != ExperimentState.RUNNING or not self.capabilities.get("stop", False):
                return self._error_response(request_id, "invalid_state", "stop is allowed only from RUNNING")
            self._stop_metadata = {"request_id": request_id, "request_monotonic_ns": now_ns,
                                   "request_utc": now_utc, "request_utc_ns": now_utc_ns,
                                   "accepted_monotonic_ns": now_ns, "accepted_utc": now_utc,
                                   "accepted_utc_ns": now_utc_ns}
            try:
                self._transition(ExperimentState.FINISHING)
            except Exception:
                self._stop_metadata = None
                raise
            self._stop.set()
            self._record("OPERATOR_COMMAND", command="stop", request_id=request_id,
                         request_monotonic_ns=now_ns, request_utc=now_utc,
                         request_utc_ns=now_utc_ns, result="accepted")
            return self._success_response(request_id)
        if command == "abort":
            if state not in {ExperimentState.PREPARING, ExperimentState.READY, ExperimentState.RUNNING} or not self.capabilities.get("abort", False):
                return self._error_response(request_id, "invalid_state", "abort is allowed only before or during RUNNING")
            self._abort_metadata = {"request_id": request_id, "request_monotonic_ns": now_ns,
                                    "request_utc": now_utc, "request_utc_ns": now_utc_ns,
                                    "accepted_monotonic_ns": now_ns, "accepted_utc": now_utc,
                                    "accepted_utc_ns": now_utc_ns}
            try:
                if state in {ExperimentState.PREPARING, ExperimentState.READY}:
                    self._transition(ExperimentState.ABORTED, reason="operator_abort_before_start")
                    self._finished.set()
                else:
                    self._transition(ExperimentState.FINISHING)
            except Exception:
                self._abort_metadata = None
                raise
            if state == ExperimentState.RUNNING:
                self._abort.set()
            self._record("OPERATOR_COMMAND", command="abort", request_id=request_id,
                         request_monotonic_ns=now_ns, request_utc=now_utc,
                         request_utc_ns=now_utc_ns, result="accepted")
            return self._success_response(request_id)
        if command == "deliver_bait":
            channel = request.get("channel")
            action = self._semantic_actions.get(command)
            if (not isinstance(channel, str) or channel not in _SEMANTIC_CHANNELS
                    or not self.capabilities.get(f"bait_{channel}", False) or action is None):
                return self._error_response(request_id, "unsupported_action", "deliver_bait is not supported")
            if state not in {ExperimentState.READY, ExperimentState.RUNNING}:
                return self._error_response(
                    request_id, "invalid_state", "deliver_bait is allowed only from READY or RUNNING"
                )
            try:
                action(channel, request_id)
            except Exception as exc:  # noqa: BLE001 - report and preserve the task process.
                self._record("OPERATOR_ACTION", command="deliver_bait", action="bait",
                             channel=channel, request_id=request_id, result="failed",
                             error=str(exc), request_monotonic_ns=now_ns, request_utc=now_utc,
                             request_utc_ns=now_utc_ns)
                return self._error_response(request_id, "action_failed", str(exc))
            self._record("OPERATOR_ACTION", command="deliver_bait", action="bait",
                         channel=channel, request_id=request_id, result="accepted",
                         request_monotonic_ns=now_ns, request_utc=now_utc,
                         request_utc_ns=now_utc_ns)
            return self._success_response(request_id)
        return self._error_response(request_id, "unknown_command", f"unknown command: {command}")

    def _run_worker(self) -> None:
        try:
            result = self._run(self)
            self._result = result
            output_path = getattr(result, "session_root", None)
            if output_path is None:
                session = getattr(result, "session", None)
                output_path = getattr(getattr(session, "context", None), "session_root", None)
            result_status = getattr(result, "status", None)
            if result_status is None:
                final_state = getattr(getattr(result, "final_state", None), "value", None)
                result_status = final_state or ("COMPLETE" if getattr(result, "ok", True) else "FAILED")
            with self._lock:
                if output_path is not None:
                    self._session_output_path = str(output_path)
                if result_status in {"ABORTED", "INTERRUPTED"}:
                    if self._lifecycle.state != ExperimentState.ABORTED:
                        self._transition(
                            ExperimentState.ABORTED,
                            reason="operator_abort" if self._abort_metadata else "protocol_aborted",
                        )
                elif result_status != "COMPLETE":
                    self._error = getattr(result, "error", None) or f"protocol ended with {result_status}"
                    if self._lifecycle.state != ExperimentState.ERROR:
                        self._transition(ExperimentState.ERROR, reason="protocol_error")
                elif self._abort.is_set():
                    self._transition(ExperimentState.ABORTED, reason="operator_abort")
                else:
                    if self._lifecycle.state == ExperimentState.RUNNING:
                        self._transition(ExperimentState.FINISHING)
                    if self._lifecycle.state == ExperimentState.FINISHING:
                        self._transition(
                            ExperimentState.COMPLETE,
                            reason="operator_stop" if self._stop_metadata else "natural_completion",
                        )
                self._finished.set()
        except BaseException as exc:  # noqa: BLE001 - also capture KeyboardInterrupt for cleanup state.
            with self._lock:
                self._error = str(exc)
                state = self._lifecycle.state
                if state not in {ExperimentState.ERROR, ExperimentState.ABORTED, ExperimentState.COMPLETE}:
                    terminal_state = (
                        ExperimentState.ABORTED
                        if isinstance(exc, KeyboardInterrupt) or self._abort.is_set()
                        else ExperimentState.ERROR
                    )
                    reason = (
                        "keyboard_interrupt" if isinstance(exc, KeyboardInterrupt)
                        else "operator_abort" if self._abort.is_set()
                        else "protocol_error"
                    )
                    try:
                        self._transition(terminal_state, reason=reason)
                    except OSError as state_error:
                        self._error = (
                            f"{self._error}; control state persistence failed: {state_error}"
                        )
                    finally:
                        self._record("CONTROL_ERROR", source="engine", error=str(exc))
                        self._finished.set()

    def _success_response(self, request_id: str | None) -> dict[str, Any]:
        status = self.status()
        return {"schema_version": CONTROL_SCHEMA_VERSION, "request_id": request_id,
                "ok": True, "state": status["state"], "status": status}

    def _error_response(self, request_id: str | None, code: str, message: str) -> dict[str, Any]:
        status = self.status()
        return {"schema_version": CONTROL_SCHEMA_VERSION, "request_id": request_id,
                "ok": False, "state": status["state"],
                "error": {"code": code, "message": message}, "status": status}

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def join(self, timeout: float | None = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)
