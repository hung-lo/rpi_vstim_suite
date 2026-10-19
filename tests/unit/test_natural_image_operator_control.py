import json
import time
from dataclasses import replace
from threading import Event

import pytest
from PIL import Image

from rpi_vstim.control import ExperimentControl, ExperimentState
from rpi_vstim.core.config import Config
from rpi_vstim.core.natural_image_demo import (
    prepare_natural_image_demo,
    run_natural_image_demo,
    write_operator_control_metadata,
)
from rpi_vstim.display.renderer import ProductionFrameRenderer


def _config(tmp_path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (4, 2), (30, 100, 180)).save(asset_root / "natimg_center_0000.png")
    base = Config()
    return replace(
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


@pytest.mark.parametrize(
    ("command", "expected_status", "expected_state"),
    [(None, "COMPLETE", ExperimentState.COMPLETE),
     ("stop", "COMPLETE", ExperimentState.COMPLETE),
     ("abort", "ABORTED", ExperimentState.ABORTED)],
)
def test_operator_natural_images_ready_start_stop_abort_and_finalize(
    tmp_path, monkeypatch, command, expected_status, expected_state
):
    config = _config(tmp_path)
    session_id = f"operator-{command or 'complete'}"
    prepared = prepare_natural_image_demo(config, session_id=session_id)
    session_root = config.paths.output_root / session_id
    assert not session_root.exists()
    entered, release = Event(), Event()
    holder = {}

    class FakeDisplay:
        def __init__(self, **_kwargs):
            self.renderer = None
            self.photodiode = None
            self.closed = False

        def open(self, display_config):
            self.renderer = ProductionFrameRenderer(
                display_config.width_px,
                display_config.height_px,
                display_config.pixel_format,
                photodiode=None,
            )

        def present_sequence(self, frames):
            values = []
            for frame in frames:
                values.append(frame)
                if frame.metadata.logical_frame_index == 1:
                    entered.set()
                    assert release.wait(1)
                if frame.metadata.logical_frame_index == 2 and command:
                    response = holder["control"].handle_request({
                        "request_id": f"{command}-during-run",
                        "command": command,
                    })
                    assert response["ok"]
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

    display_instances = []
    original_init = FakeDisplay.__init__

    def record_display(self, **kwargs):
        original_init(self, **kwargs)
        display_instances.append(self)

    FakeDisplay.__init__ = record_display
    monkeypatch.setattr("rpi_vstim.core.natural_image_demo.KmsDisplayBackend", FakeDisplay)

    control = ExperimentControl(
        session_id=session_id,
        protocol="natural-images",
        planned_duration_s=prepared.plan.total_frames / config.display.refresh_hz,
        run=lambda active: run_natural_image_demo(
            config,
            mouse_id="simulation-test",
            session_id=session_id,
            prepared=prepared,
            control=active,
        ),
    )
    holder["control"] = control
    control.mark_ready()
    assert control.status()["state"] == "READY"
    assert control.status()["capabilities"] == {
        "start": True,
        "stop": False,
        "abort": True,
        "pause": False,
        "bait_left": False,
        "bait_right": False,
        "bait_center": False,
    }
    assert display_instances == []

    accepted = control.handle_request({"request_id": "start-1", "command": "start"})
    assert accepted["ok"]
    assert entered.wait(1)
    assert control.status()["state"] == "RUNNING"
    release.set()
    assert control.wait(2)
    control.join()
    write_operator_control_metadata(session_root, control.provenance())

    assert control.state == expected_state
    assert control.result.status == expected_status
    assert display_instances[0].closed
    events = [
        json.loads(line)
        for line in (session_root / "events.jsonl").read_text().splitlines()
    ]
    assert any(item["event"] == "OPERATOR_COMMAND" and item["command"] == "start" for item in events)
    start_index = next(
        index for index, item in enumerate(events)
        if item["event"] == "OPERATOR_COMMAND" and item["command"] == "start"
    )
    assert start_index < next(
        index for index, item in enumerate(events) if item["event"] == "SESSION_START"
    )
    if command:
        assert any(item["event"] == "OPERATOR_COMMAND" and item["command"] == command for item in events)
    assert (session_root / "final_status.json").is_file()
    assert json.loads((session_root / "operator_control.json").read_text())["state"] == expected_state.value
    assert json.loads((session_root / "final_status.json").read_text())["status"] == expected_status


def test_operator_natural_images_failure_is_not_complete_and_closes_display(tmp_path, monkeypatch):
    config = _config(tmp_path)
    session_id = "operator-display-failure"
    prepared = prepare_natural_image_demo(config, session_id=session_id)

    class FailedDisplay:
        renderer = None
        photodiode = None

        def open(self, _config):
            self.renderer = ProductionFrameRenderer(4, 2, config.display.pixel_format)

        def present_sequence(self, _frames):
            raise RuntimeError("injected KMS presentation failure")

        def close(self):
            self.closed = True

    display = FailedDisplay()
    monkeypatch.setattr(
        "rpi_vstim.core.natural_image_demo.KmsDisplayBackend", lambda **_kwargs: display
    )
    control = ExperimentControl(
        session_id=session_id,
        protocol="natural-images",
        run=lambda active: run_natural_image_demo(
            config, mouse_id="simulation-test", session_id=session_id,
            prepared=prepared, control=active,
        ),
    )
    control.mark_ready()
    control.handle_request({"request_id": "start-fail", "command": "start"})
    assert control.wait(2)
    control.join()
    write_operator_control_metadata(control.result.session_root, control.provenance())
    assert control.state == ExperimentState.ERROR
    assert control.result.status == "FAILED"
    assert display.closed
    final = json.loads((control.result.session_root / "final_status.json").read_text())
    assert final["status"] == "FAILED"
