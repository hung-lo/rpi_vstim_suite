import json
import time
from dataclasses import replace

from PIL import Image
import pytest

from rpi_vstim.audio import AudioError, FakeAudio
from rpi_vstim.camera.identity import ResolvedCamera
from rpi_vstim.camera.supervisor import CameraCaptureSpec, build_rpicam_command
from rpi_vstim.core.config import Config
from rpi_vstim.core.natural_image_demo import AudioCoexistenceSettings, run_natural_image_demo
from rpi_vstim.display.renderer import ProductionFrameRenderer


def test_preview_command_is_native_and_side_by_side(tmp_path):
    spec = CameraCaptureSpec(
        "camera0",
        "camera_0",
        "serial0",
        True,
        "rpicam",
        (),
        requested_width_px=640,
        requested_height_px=480,
        requested_fps=30.0,
        pixel_format_or_codec="h264",
        preview_enabled=True,
        preview_geometry=(0, 0, 512, 384),
        preview_connector="HDMI-A-1",
    )
    command = build_rpicam_command(
        spec,
        tmp_path / "capture.h264",
        resolved_camera=ResolvedCamera("camera0", "serial0", "imx708", "0", "topology0"),
    )
    assert "--nopreview" not in command
    assert command[command.index("--preview") + 1] == "0,0,512,384"
    assert "--timeout" in command
    assert "--camera" in command and "/dev/video0" not in command


def test_natural_demo_is_hardware_free_without_licks_or_cameras(tmp_path, monkeypatch):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    image_path = asset_root / "natimg_center_0000.png"
    Image.new("RGB", (4, 2), (30, 100, 180)).save(image_path)
    config = replace(
        Config(),
        paths=replace(Config().paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
        display=replace(
            Config().display,
            backend="kms",
            ownership="lease",
            stimulus_connector="HDMI-A-2",
            width_px=4,
            height_px=2,
            refresh_hz=60.0,
            preview_connector="HDMI-A-1",
        ),
        photodiode=replace(Config().photodiode, size_px=1),
        protocol=replace(
            Config().protocol,
            name="natural-images",
            parameters={
                "image_count": 1,
                "image_duration_s": 1 / 60,
                "iti_frames": (1,),
                "initial_gray_frames": 1,
                "final_gray_frames": 1,
            },
        ),
    )

    class FakeDisplay:
        def __init__(self, **_kwargs):
            self.photodiode = None
            self.renderer = None
            self.closed = False

        def open(self, display_config):
            self.config = display_config
            self.renderer = ProductionFrameRenderer(
                display_config.width_px,
                display_config.height_px,
                display_config.pixel_format,
                photodiode=self.photodiode,
            )

        def present_sequence(self, frames):
            values = list(frames)
            assert [item.metadata.logical_frame_index for item in values] == list(range(len(values)))
            assert [item.metadata.producer_sequence for item in values] == list(range(len(values)))
            return {
                "connector": "HDMI-A-2",
                "ownership": "lease-active",
                "requested_frame_count": len(values),
                "completed_frame_count": len(values),
                "first_page_flip_callback_monotonic_ns": 1_000_000_000,
                "last_page_flip_callback_monotonic_ns": 1_000_000_000 + len(values) * 16_666_666,
                "restored": True,
                "ownership_lifecycle": {
                    "lease_acquire_count": 1,
                    "modeset_count": 1,
                    "restore_count": 1,
                    "lease_release_count": 1,
                },
                "flip_events": [
                    {
                        "frame_index": index,
                        "kernel_sequence": index + 1,
                        "kernel_event_ns": 2_000_000_000 + index * 16_666_666,
                        "callback_monotonic_ns": 1_000_000_000 + index * 16_666_666,
                        "callback_realtime_ns": 3_000_000_000 + index * 16_666_666,
                    }
                    for index in range(len(values))
                ],
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr("rpi_vstim.core.natural_image_demo.KmsDisplayBackend", FakeDisplay)
    result = run_natural_image_demo(
        config,
        mouse_id="V1_2",
        session_id="demo-test",
        use_licks=False,
        use_cameras=False,
    )
    assert result.ok
    assert result.raw_lick_count == {"lick_left": 0, "lick_right": 0}
    records = [
        json.loads(line)
        for line in (result.session_root / "events.jsonl").read_text().splitlines()
    ]
    assert {record["event"] for record in records} >= {
        "SESSION_START",
        "CLOCK_SYNC",
        "GRAY_ONSET",
        "IMAGE_ONSET",
        "IMAGE_OFFSET",
        "DISPLAY_RELEASED",
        "SESSION_END",
    }
    assert all(
        {"utc_time", "utc_ns", "monotonic_ns", "session_elapsed_s"} <= record.keys()
        for record in records
    )
    assert not (result.session_root / "events.jsonl").read_text().count("reward_")


def test_clock_mapping_is_persisted_in_event_log(tmp_path):
    from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream

    clock = SessionClock("clock-test", 10_000, 20_000)
    stream = UnifiedEventStream(tmp_path / "events.jsonl", session_id="clock-test", clock=clock)
    assert stream.emit("TEST", source_monotonic_ns=20_250)
    stream.emit("CLOCK_SYNC", source_monotonic_ns=20_000, **clock.sync_fields())
    diagnostics = stream.close()
    assert diagnostics["dropped_count"] == 0
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert records[0]["utc_ns"] == 10_250
    assert records[0]["session_elapsed_s"] == 0.00000025
    assert records[1]["clock_realtime_ns"] == 10_000


@pytest.mark.parametrize("fail_audio", [False, True])
def test_natural_demo_audio_coexistence_finalizes_and_propagates_failure(
    tmp_path, monkeypatch, fail_audio
):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    Image.new("RGB", (4, 2), (30, 100, 180)).save(asset_root / "natimg_center_0000.png")
    config = replace(
        Config(),
        paths=replace(Config().paths, asset_root=asset_root, output_root=tmp_path / "sessions"),
        display=replace(
            Config().display,
            backend="kms",
            ownership="lease",
            stimulus_connector="HDMI-A-2",
            width_px=4,
            height_px=2,
            refresh_hz=60.0,
            preview_connector="HDMI-A-1",
        ),
        photodiode=replace(Config().photodiode, size_px=1),
        protocol=replace(
            Config().protocol,
            name="natural-images",
            parameters={
                "image_count": 1,
                "image_duration_s": 1 / 60,
                "iti_frames": (1,),
                "initial_gray_frames": 179,
                "final_gray_frames": 1,
            },
        ),
    )

    displays = []

    class FakeDisplay:
        def __init__(self, **_kwargs):
            self.photodiode = None
            self.renderer = None
            self.closed = False
            displays.append(self)

        def open(self, display_config):
            self.renderer = ProductionFrameRenderer(
                display_config.width_px,
                display_config.height_px,
                display_config.pixel_format,
                photodiode=self.photodiode,
            )

        def present_sequence(self, frames):
            values = list(frames)
            start_mono = time.monotonic_ns()
            start_utc = time.time_ns()
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
                "ownership_lifecycle": {
                    "lease_acquire_count": 1,
                    "modeset_count": 1,
                    "restore_count": 1,
                    "lease_release_count": 1,
                },
                "flip_events": flips,
            }

        def close(self):
            self.closed = True

    class TestAudio(FakeAudio):
        def play(self, stimulus_id):
            if fail_audio:
                raise AudioError("injected coexistence playback failure")
            return super().play(stimulus_id)

    monkeypatch.setattr("rpi_vstim.core.natural_image_demo.KmsDisplayBackend", FakeDisplay)
    audio = TestAudio()
    settings = AudioCoexistenceSettings(
        "USB Audio Device", sequence=("beep",), start_delay_s=0.0, interval_s=3.0
    )
    result = run_natural_image_demo(
        config,
        mouse_id="simulation-test",
        session_id=f"audio-av-{fail_audio}",
        use_licks=False,
        use_cameras=False,
        audio=audio,
        audio_settings=settings,
    )

    expected_status = "FAILED" if fail_audio else "COMPLETE"
    assert result.status == expected_status
    assert audio.closed and displays[0].closed
    records = [
        json.loads(line)
        for line in (result.session_root / "events.jsonl").read_text().splitlines()
    ]
    names = [record["event"] for record in records]
    assert names.index("AUDIO_PREPARED") < names.index("AV_ACQUISITION_START")
    assert names.index("AUDIO_TRIAL_START") < names.index("AUDIO_REQUEST")
    assert names.index("AUDIO_REQUEST") < names.index("AUDIO_TRIAL_END")
    assert "AUDIO_SUMMARY" in names
    assert audio.played == ([] if fail_audio else ["beep"])
    summary = json.loads((result.session_root / "audio_summary.json").read_text())
    assert summary["planned_sounds"] == 1
    assert bool(summary["errors"]) is fail_audio
    manifest = json.loads((result.session_root / "audio_manifest.json").read_text())
    assert manifest["schedule_order"] == ["beep"]
    assert manifest["stimuli"] and all(item["sha256"] for item in manifest["stimuli"])
    assert json.loads((result.session_root / "final_status.json").read_text())["status"] == expected_status
