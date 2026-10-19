import json
import os
import socket
import threading
import time
from dataclasses import replace
from typing import ClassVar

from PIL import Image

from rpi_vstim import cli
from rpi_vstim.core.config import Config
from rpi_vstim.display.renderer import ProductionFrameRenderer


def _send(path, value):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path))
        client.sendall(json.dumps(value).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            response.extend(client.recv(4096))
        return json.loads(response.split(b"\n", 1)[0])


def _until_ready(path, thread, result):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise AssertionError(f"CLI exited before READY: {result}")
        try:
            status = _send(path, {"command": "status"})["status"]
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.01)
            continue
        if status["state"] == "READY":
            return status
        time.sleep(0.01)
    raise AssertionError("operator-controlled CLI did not become READY")


def test_natural_image_cli_operator_control_is_opt_in_and_reconnectable(tmp_path, monkeypatch):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (4, 2), (30, 100, 180)).save(asset_root / "natimg_center_0000.png")
    base = Config()
    config = replace(
        base,
        paths=replace(base.paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
        display=replace(
            base.display,
            backend="kms",
            ownership="lease",
            stimulus_connector="HDMI-A-2",
            width_px=4,
            height_px=2,
            refresh_hz=60.0,
            preview_connector="HDMI-A-1",
        ),
        photodiode=replace(base.photodiode, size_px=1),
        protocol=replace(
            base.protocol,
            name="natural-images",
            parameters={
                "image_count": 1,
                "image_duration_s": 2 / 60,
                "iti_frames": (1,),
                "initial_gray_frames": 1,
                "final_gray_frames": 1,
            },
        ),
    )

    class FakeDisplay:
        instances: ClassVar[list[object]] = []

        def __init__(self, **_kwargs):
            self.renderer = None
            self.photodiode = None
            self.closed = False
            self.entered = threading.Event()
            self.release = threading.Event()
            self.instances.append(self)

        def open(self, display_config):
            self.renderer = ProductionFrameRenderer(
                display_config.width_px, display_config.height_px,
                display_config.pixel_format, photodiode=None,
            )

        def present_sequence(self, frames):
            values = []
            for frame in frames:
                values.append(frame)
                if frame.metadata.logical_frame_index == 1:
                    self.entered.set()
                    assert self.release.wait(2)
            start_mono, start_utc = time.monotonic_ns(), time.time_ns()
            flips = [
                {
                    "frame_index": index,
                    "kernel_sequence": index + 1,
                    "kernel_event_ns": start_mono + index * 16_666_667,
                    "callback_monotonic_ns": start_mono + index * 16_666_667,
                    "callback_realtime_ns": start_utc + index * 16_666_667,
                }
                for index in range(len(values))
            ]
            return {
                "connector": "HDMI-A-2",
                "ownership": "lease-active",
                "requested_frame_count": len(values),
                "completed_frame_count": len(values),
                "first_page_flip_callback_monotonic_ns": start_mono,
                "last_page_flip_callback_monotonic_ns": flips[-1]["callback_monotonic_ns"],
                "restored": True,
                "ownership_lifecycle": {"lease_acquire_count": 1, "restore_count": 1},
                "flip_events": flips,
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "display_probe", lambda _config: "read-only fake probe")
    monkeypatch.setattr("rpi_vstim.core.natural_image_demo.KmsDisplayBackend", FakeDisplay)

    direct_args = cli.build_parser().parse_args(["natural-images", "run", "--mouse-id", "test"])
    assert direct_args.operator_control is False
    assert direct_args.simulate is False
    assert direct_args.control_socket is None
    assert direct_args.control_state_file is None

    session_id = f"cli-operator-{os.getpid()}"
    socket_path = f"/tmp/rpi-vstim-cli-{os.getpid()}.sock"
    state_path = tmp_path / "operator-state.json"
    result = {}
    thread = threading.Thread(
        target=lambda: result.setdefault(
            "exit_code",
            cli.main([
                "natural-images", "run", "--mouse-id", "simulation-test",
                "--config", "unused.toml", "--session-id", session_id,
                "--operator-control", "--control-socket", socket_path,
                "--control-state-file", str(state_path),
            ]),
        ),
        daemon=True,
    )
    thread.start()
    try:
        ready = _until_ready(socket_path, thread, result)
        assert ready["session"]["id"] == session_id
        assert not (config.paths.output_root / session_id).exists()
        assert FakeDisplay.instances == []
        assert _send(socket_path, {"command": "status"})["status"]["state"] == "READY"
        start = _send(socket_path, {"request_id": "monitor-start", "command": "start"})
        assert start["ok"]
        deadline = time.monotonic() + 2
        while not FakeDisplay.instances and time.monotonic() < deadline:
            time.sleep(0.005)
        assert FakeDisplay.instances
        display = FakeDisplay.instances[0]
        assert display.entered.wait(2)
        assert _send(socket_path, {"command": "status"})["status"]["state"] == "RUNNING"
        stop = _send(socket_path, {"request_id": "monitor-stop", "command": "stop"})
        assert stop["ok"] and stop["state"] == "FINISHING"
        display.release.set()
        thread.join(3)
        assert not thread.is_alive()
        assert result["exit_code"] == 0
        assert display.closed
        assert not os.path.exists(socket_path)
        durable = json.loads(state_path.read_text())
        assert durable["state"] == "COMPLETE" and durable["terminal"]
        assert durable["session_id"] == session_id
        assert durable["protocol"] == "natural-images"
        assert durable["terminal_request_id"] == "monitor-stop"
        assert durable["control_instance_id"]
        session_root = config.paths.output_root / session_id
        assert json.loads((session_root / "final_status.json").read_text())["status"] == "COMPLETE"
        control = json.loads((session_root / "operator_control.json").read_text())
        assert control["state"] == "COMPLETE"
        assert control["start"]["request_id"] == "monitor-start"
        assert control["stop"]["request_id"] == "monitor-stop"
    finally:
        for instance in FakeDisplay.instances:
            instance.release.set()
        if thread.is_alive():
            thread.join(3)
