from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from PIL import Image

from rpi_vstim import cli
from rpi_vstim.core import natural_image_demo
from rpi_vstim.core.config import Config, load_config
from rpi_vstim.display.fake import FakeDisplayBackend


def _send(path: Path, value: dict[str, object]) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path))
        client.sendall(json.dumps(value).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            response.extend(client.recv(4096))
        return json.loads(response.split(b"\n", 1)[0])


def _wait_ready(path: Path, thread: threading.Thread, result: dict[str, int]) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise AssertionError(f"simulated CLI exited before READY: {result}")
        try:
            status = _send(path, {"command": "status"})["status"]
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.01)
            continue
        if status["state"] == "READY":
            return status
        time.sleep(0.01)
    raise AssertionError("simulated Natural Images command did not become READY")


def _config(tmp_path: Path) -> Config:
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (4, 2), (30, 100, 180)).save(assets / "natimg_center_0000.png")
    base = Config()
    return replace(
        base,
        paths=replace(base.paths, asset_root=assets, output_root=tmp_path / "sessions"),
        display=replace(
            base.display,
            backend="kms",
            ownership="lease",
            stimulus_connector="HDMI-A-2",
            width_px=8,
            height_px=4,
            refresh_hz=60.0,
            preview_connector="HDMI-A-1",
        ),
        photodiode=replace(base.photodiode, size_px=1),
        protocol=replace(
            base.protocol,
            name="natural-images",
            parameters={
                "image_count": 1,
                "image_duration_s": 3.0,
                "iti_frames": (0, 0),
                "initial_gray_frames": 0,
                "final_gray_frames": 0,
            },
        ),
    )


def _forbid_hardware(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("hardware access was attempted in --simulate mode")

    monkeypatch.setattr(cli, "display_probe", forbidden)
    monkeypatch.setattr(cli, "KmsDisplayBackend", forbidden)
    monkeypatch.setattr(cli, "SoundDeviceAudio", forbidden)
    monkeypatch.setattr(natural_image_demo, "KmsDisplayBackend", forbidden)
    monkeypatch.setattr(natural_image_demo, "LgpioLickMonitor", forbidden)
    monkeypatch.setattr(natural_image_demo, "LocalCameraSupervisor", forbidden)


def _launch(
    monkeypatch,
    config: Config,
    *,
    session_id: str,
    socket_path: Path,
    output_root: Path,
    extra: tuple[str, ...] = (),
) -> tuple[threading.Thread, dict[str, int]]:
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    result: dict[str, int] = {}
    argv = [
        "natural-images", "run", "--mouse-id", "simulation",
        "--config", "unused.toml", "--session-id", session_id,
        "--output-root", str(output_root), "--operator-control", "--simulate",
        "--control-socket", str(socket_path), *extra,
    ]
    thread = threading.Thread(
        target=lambda: result.setdefault("exit_code", cli.main(argv)), daemon=True
    )
    thread.start()
    return thread, result


def test_natural_image_simulation_profile_is_hardware_independent():
    path = Path(__file__).resolve().parents[2] / "config/rigs/natural_images.operator_simulation.toml"
    config = load_config(path)
    assert config.display.backend == "fake"
    assert config.hardware.backend == "simulated"
    assert config.session.simulation is True
    assert config.paths.asset_root.is_dir()
    assert config.protocol.parameters["image_count"] == 5


def test_operator_simulation_ready_reconnect_start_stop_and_telemetry(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    _forbid_hardware(monkeypatch)

    class TrackedFakeDisplay(FakeDisplayBackend):
        instances: ClassVar[list[TrackedFakeDisplay]] = []

        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.closed = False
            self.instances.append(self)

        def present_sequence(self, frames):
            self.started.set()
            return super().present_sequence(frames)

        def close(self):
            self.closed = True
            super().close()

    monkeypatch.setattr(natural_image_demo, "FakeDisplayBackend", TrackedFakeDisplay)
    session_id = f"sim-stop-{os.getpid()}"
    socket_path = tmp_path / "operator.sock"
    output_root = tmp_path / "sessions"
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    telemetry_port = receiver.getsockname()[1]
    thread, result = _launch(
        monkeypatch,
        config,
        session_id=session_id,
        socket_path=socket_path,
        output_root=output_root,
        extra=("--telemetry-port", str(telemetry_port)),
    )
    try:
        ready = _wait_ready(socket_path, thread, result)
        assert ready["session"]["id"] == session_id
        assert not (output_root / session_id).exists()
        assert TrackedFakeDisplay.instances == []

        telemetry = json.loads(receiver.recv(4096))
        assert telemetry["lifecycle"] == "READY"
        assert telemetry["session"]["id"] == session_id
        assert _send(socket_path, {"command": "status"})["status"]["state"] == "READY"

        start_request = {"request_id": "start-one", "command": "start"}
        started = _send(socket_path, start_request)
        assert started["ok"] and started["state"] == "RUNNING"
        assert _send(socket_path, start_request) == started
        deadline = time.monotonic() + 2
        while not TrackedFakeDisplay.instances and time.monotonic() < deadline:
            time.sleep(0.005)
        assert TrackedFakeDisplay.instances
        assert TrackedFakeDisplay.instances[0].started.wait(2)
        time.sleep(0.05)
        running = _send(socket_path, {"command": "status"})["status"]
        assert running["state"] == "RUNNING"
        assert running["elapsed_s"] >= 0
        assert running["eta_s"] is not None

        stop_request = {"request_id": "stop-one", "command": "stop"}
        stopped = _send(socket_path, stop_request)
        assert stopped["ok"] and stopped["state"] == "FINISHING"
        assert _send(socket_path, stop_request) == stopped
        thread.join(5)
        assert not thread.is_alive()
        assert result["exit_code"] == 0

        session_root = output_root / session_id
        final = json.loads((session_root / "final_status.json").read_text())
        manifest = json.loads((session_root / "session_manifest.json").read_text())
        provenance = json.loads((session_root / "provenance.json").read_text())
        resource = json.loads((session_root / "resource_summary.json").read_text())
        display_record = json.loads((session_root / "display_results.jsonl").read_text().splitlines()[0])
        events = [json.loads(line) for line in (session_root / "events.jsonl").read_text().splitlines()]
        assert final["status"] == "COMPLETE"
        assert final["natural_image_demo"]["simulated"] is True
        assert final["natural_image_demo"]["display_backend"] == "simulated"
        assert final["natural_image_demo"]["gpio_used"] == []
        assert manifest["simulated"] is True
        assert provenance["natural_image_demo"]["physical_kms_trace"] is False
        assert resource["simulated"] is True
        assert resource["display_backend"] == "simulated"
        assert display_record["simulated"] is True
        assert display_record["physical_kms_trace"] is False
        assert display_record.get("first_page_flip_kernel_event_ns") is None
        session_start = next(event for event in events if event["event"] == "SESSION_START")
        assert session_start["simulated"] is True
        assert session_start["display_backend"] == "simulated"
        assert any(event["event"] == "SIMULATED_DISPLAY_REQUEST" for event in events)
        assert not any(event["event"] == "DISPLAY_ACQUIRE_REQUEST" for event in events)
        assert not any(event["event"] == "DISPLAY_TRACE_COMPLETE" for event in events)
        assert any(event["event"] == "SIMULATED_DISPLAY_COMPLETE" for event in events)
        assert all(
            event.get("timing_source") != "drm_kernel_vblank_monotonic"
            for event in events
        )
        assert TrackedFakeDisplay.instances[0].closed
    finally:
        receiver.close()
        if thread.is_alive():
            _send(socket_path, {"request_id": "cleanup-abort", "command": "abort"})
            thread.join(3)


def test_operator_simulation_abort_from_ready_is_idempotent_and_creates_no_session(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    _forbid_hardware(monkeypatch)
    session_id = f"sim-abort-ready-{os.getpid()}"
    output_root = tmp_path / "sessions"
    socket_path = tmp_path / "operator.sock"
    thread, result = _launch(
        monkeypatch,
        config,
        session_id=session_id,
        socket_path=socket_path,
        output_root=output_root,
    )
    _wait_ready(socket_path, thread, result)
    request = {"request_id": "abort-ready", "command": "abort"}
    aborted = _send(socket_path, request)
    assert aborted["ok"] and aborted["state"] == "ABORTED"
    thread.join(3)
    assert not thread.is_alive()
    assert result["exit_code"] == 130
    assert not (output_root / session_id).exists()


def test_operator_simulation_abort_while_running_finalizes_aborted_session(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    _forbid_hardware(monkeypatch)
    session_id = f"sim-abort-running-{os.getpid()}"
    output_root = tmp_path / "sessions"
    socket_path = tmp_path / "operator.sock"
    thread, result = _launch(
        monkeypatch,
        config,
        session_id=session_id,
        socket_path=socket_path,
        output_root=output_root,
    )
    _wait_ready(socket_path, thread, result)
    started = _send(socket_path, {"request_id": "start-running", "command": "start"})
    assert started["ok"] and started["state"] == "RUNNING"
    time.sleep(0.05)
    assert _send(socket_path, {"command": "status"})["status"]["state"] == "RUNNING"
    request = {"request_id": "abort-running", "command": "abort"}
    aborted = _send(socket_path, request)
    assert aborted["ok"] and aborted["state"] == "FINISHING"
    assert _send(socket_path, request) == aborted
    thread.join(5)
    assert not thread.is_alive()
    assert result["exit_code"] == 130
    final = json.loads((output_root / session_id / "final_status.json").read_text())
    assert final["status"] == "ABORTED"


def test_natural_image_simulation_cli_requires_explicit_output_root(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    args = cli.build_parser().parse_args(
        ["natural-images", "run", "--mouse-id", "simulation", "--simulate"]
    )
    assert args.simulate is True
    assert args.operator_control is False
    assert cli.main([
        "natural-images", "run", "--mouse-id", "simulation", "--simulate"
    ]) == 2
