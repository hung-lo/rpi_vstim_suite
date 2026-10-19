import json
import socket
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from rpi_vstim.control import (
    ExperimentControl,
    ExperimentLifecycle,
    ExperimentState,
    LifecycleError,
    UnixControlServer,
)


def _request(path, payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path))
        client.sendall(json.dumps(payload).encode() + b"\n")
        received = bytearray()
        while b"\n" not in received:
            received.extend(client.recv(4096))
        return json.loads(received.split(b"\n", 1)[0])


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert predicate()


def _request_payload(request_id, command, **fields):
    return {"schema_version": 1, "request_id": request_id, "command": command, **fields}


def test_lifecycle_accepts_only_documented_transitions():
    lifecycle = ExperimentLifecycle()
    lifecycle.transition(ExperimentState.READY)
    lifecycle.transition(ExperimentState.RUNNING)
    lifecycle.transition(ExperimentState.FINISHING)
    lifecycle.transition(ExperimentState.COMPLETE)
    with pytest.raises(LifecycleError):
        lifecycle.transition(ExperimentState.RUNNING)


def test_unimplemented_or_unknown_capabilities_cannot_be_advertised():
    with pytest.raises(ValueError, match="pause control is not implemented"):
        ExperimentControl(
            session_id="pause-capability",
            protocol="fake-task",
            run=lambda _control: None,
            capabilities={"pause": True},
        )
    with pytest.raises(ValueError, match="unsupported operator capability"):
        ExperimentControl(
            session_id="unknown-capability",
            protocol="fake-task",
            run=lambda _control: None,
            capabilities={"execute_shell": True},
        )


def test_socket_reconnect_and_disconnect_do_not_change_experiment(tmp_path):
    started, release = threading.Event(), threading.Event()
    runs = []

    def run(control):
        runs.append(1)
        started.set()
        release.wait(1)
        return SimpleNamespace(status="COMPLETE")

    control = ExperimentControl(session_id="reconnect", protocol="natural-images", run=run)
    control.mark_ready()
    path = tmp_path / "control.sock"
    server = UnixControlServer(path, control.handle_request)
    server.start()
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        ready = _request(path, {"schema_version": 1, "command": "status"})
        assert ready["status"]["state"] == "READY"
        start = _request(path, {"request_id": "start-a", "command": "start"})
        assert start["ok"]
        assert started.wait(1)
        # A fresh connection recovers the same running engine after the first client is gone.
        running = _request(path, {"schema_version": 1, "command": "status"})
        assert running["status"]["session"]["id"] == "reconnect"
        assert running["status"]["protocol"] == "natural-images"
        assert running["status"]["state"] == "RUNNING"
        assert running["status"]["capabilities"]["start"] is False
        assert running["status"]["capabilities"]["stop"] is True
        duplicate = _request(path, _request_payload("start-a", "start"))
        assert duplicate == start
        conflict = _request(path, _request_payload("start-a", "stop"))
        assert not conflict["ok"]
        assert conflict["error"]["code"] == "request_id_conflict"
        stopped = _request(path, _request_payload("stop-a", "stop"))
        assert stopped["state"] == "FINISHING"
        assert _request(path, _request_payload("stop-a", "stop")) == stopped
        release.set()
        assert control.wait(1)
        assert control.state == ExperimentState.COMPLETE
        assert len(runs) == 1
        elapsed = control.status()["elapsed_s"]
        time.sleep(0.01)
        assert control.status()["elapsed_s"] == elapsed
    finally:
        release.set()
        server.close()
    assert not path.exists()


def test_abort_from_ready_does_not_start_protocol(tmp_path):
    ran = []
    control = ExperimentControl(
        session_id="ready-abort", protocol="natural-images", run=lambda _control: ran.append(True)
    )
    control.mark_ready()
    response = control.handle_request(_request_payload("abort-ready", "abort"))
    assert response["ok"] and response["state"] == "ABORTED"
    assert control.wait(0)
    assert ran == []


def test_abort_running_and_keyboard_interrupt_end_aborted():
    def run(control):
        while not control.abort_requested:
            time.sleep(0.001)
        return SimpleNamespace(status="ABORTED")

    control = ExperimentControl(session_id="abort-running", protocol="natural-images", run=run)
    control.mark_ready()
    control.handle_request(_request_payload("start", "start"))
    response = control.handle_request(_request_payload("abort", "abort"))
    assert response["ok"] and response["state"] == "FINISHING"
    assert control.wait(1)
    assert control.state == ExperimentState.ABORTED

    interrupted = ExperimentControl(
        session_id="keyboard", protocol="natural-images", run=lambda _control: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    interrupted.mark_ready()
    interrupted.handle_request(_request_payload("start-k", "start"))
    assert interrupted.wait(1)
    assert interrupted.state == ExperimentState.ABORTED


def test_semantic_action_is_advertised_logged_and_idempotent():
    release = threading.Event()
    calls, events = [], []

    def action(channel, request_id):
        calls.append((channel, request_id))
        return {"delivered": True}

    def run(_control):
        release.wait(1)
        return SimpleNamespace(status="COMPLETE")

    control = ExperimentControl(
        session_id="semantic", protocol="fake-task", run=run,
        capabilities={"bait_left": True}, semantic_actions={"deliver_bait": action},
    )
    control.bind_event_sink(events.append)
    control.mark_ready()
    request = _request_payload("bait-ready", "deliver_bait", channel="left")
    accepted = control.handle_request(request)
    assert accepted["ok"]
    assert control.handle_request(request) == accepted
    assert calls == [("left", "bait-ready")]
    control.handle_request(_request_payload("start", "start"))
    _wait_for(lambda: control.state == ExperimentState.RUNNING)
    request = _request_payload("bait-1", "deliver_bait", channel="left")
    accepted = control.handle_request(request)
    assert accepted["ok"]
    assert control.handle_request(request) == accepted
    assert calls == [("left", "bait-ready"), ("left", "bait-1")]
    assert any(item["event"] == "OPERATOR_ACTION" and item["source"] == "operator" for item in events)
    rejected = control.handle_request(_request_payload("bait-2", "deliver_bait", channel="right"))
    assert rejected["error"]["code"] == "unsupported_action"
    release.set()
    assert control.wait(1)


def test_requests_fail_safely_and_multiple_start_clients_are_serialized(tmp_path):
    started, release = threading.Event(), threading.Event()
    count = []

    def run(_control):
        count.append(1)
        started.set()
        release.wait(1)
        return SimpleNamespace(status="COMPLETE")

    control = ExperimentControl(session_id="serial", protocol="natural-images", run=run)
    control.mark_ready()
    path = tmp_path / "serial.sock"
    with UnixControlServer(path, control.handle_request):
        malformed = _request(path, {"schema_version": 2, "command": "status"})
        assert malformed["error"]["code"] == "unsupported_schema"
        invalid = _request(path, _request_payload("stop-first", "stop"))
        assert invalid["error"]["code"] == "invalid_state"

        def issue(index):
            return _request(path, _request_payload(f"start-{index}", "start"))

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(issue, (1, 2)))
        assert sum(response["ok"] for response in responses) == 1
        assert started.wait(1)
        assert len(count) == 1
        release.set()
        assert control.wait(1)
        unknown = control.handle_request(_request_payload("unknown", "shell", command_text="false"))
        assert unknown["error"]["code"] == "invalid_request"


def test_malformed_socket_payload_gets_error_and_server_survives(tmp_path):
    control = ExperimentControl(session_id="malformed", protocol="natural-images", run=lambda _c: None)
    path = tmp_path / "malformed.sock"
    with UnixControlServer(path, control.handle_request):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(path))
            client.sendall(b"not-json\n")
            response = json.loads(client.recv(4096))
            assert response["ok"] is False
        assert _request(path, {"schema_version": 1, "command": "status"})["status"]["state"] == "PREPARING"


def test_monitor_request_envelope_and_control_socket_loss(tmp_path):
    release = threading.Event()
    control = ExperimentControl(
        session_id="monitor-contract",
        protocol="natural-images",
        run=lambda _control: (release.wait(1), SimpleNamespace(status="COMPLETE"))[1],
    )
    control.mark_ready()
    path = tmp_path / "monitor.sock"
    server = UnixControlServer(path, control.handle_request)
    server.start()
    status = _request(path, {"command": "status"})
    assert status["status"]["lifecycle"] == "READY"
    assert status["status"]["session"]["id"] == "monitor-contract"
    path.unlink()
    assert control.state == ExperimentState.READY
    server.close()


def test_control_command_exception_is_cached_to_prevent_retry(tmp_path):
    calls = []
    finish = threading.Event()

    def action(channel, request_id):
        calls.append((channel, request_id))

    control = ExperimentControl(
        session_id="idempotent-error",
        protocol="fake-task",
        run=lambda _control: (finish.wait(1), SimpleNamespace(status="COMPLETE"))[1],
        capabilities={"bait_left": True},
        semantic_actions={"deliver_bait": action},
    )
    control.mark_ready()
    control.handle_request(_request_payload("start", "start"))
    control._event_sink = lambda _item: (_ for _ in ()).throw(RuntimeError("event sink failed"))
    request = _request_payload("bait-error", "deliver_bait", channel="left")
    first = control.handle_request(request)
    second = control.handle_request(request)
    assert first == second
    assert first["error"]["code"] == "command_failed"
    assert calls == [("left", "bait-error")]
    finish.set()
    assert control.wait(1)
