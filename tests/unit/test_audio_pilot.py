"""Audio pilot planning and session tests without an output device."""

import json
import sys
import threading
import time
from collections import Counter
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from rpi_vstim.audio import (
    AudioError,
    FakeAudio,
    SoundDeviceAudio,
    load_pilot_clips,
    select_output_device,
)
from rpi_vstim.core.config import load_config
from rpi_vstim.core.natural_image_demo import (
    AudioCoexistenceSettings,
    _play_coexistence_audio,
    build_audio_coexistence_plan,
)
from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream
from rpi_vstim.protocols.audio_pilot import AudioPilotSettings, build_plan, run_audio_pilot

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "config/rigs/pi5_audio_pilot.example.toml"
ASSETS = ROOT / "assets/audio/pilot"


def test_plan_is_balanced_deterministic_and_bounded():
    settings = AudioPilotSettings.from_config(load_config(PROFILE))
    first = build_plan(settings)
    assert len(first) == 30
    assert Counter(trial.stimulus_id for trial in first) == {
        "beep": 10, "buzz": 10, "white_noise": 10,
    }
    assert first == build_plan(settings)
    assert first != build_plan(replace(settings, seed=settings.seed + 1))
    assert all(1.0 <= trial.iti_after_s <= 2.0 for trial in first[:-1])
    assert first[-1].iti_after_s == 0
    assert len(build_plan(replace(settings, repeats_per_stimulus=2))) == 6


def test_coexistence_schedule_is_fixed_and_fits_two_minute_plan():
    clips = load_pilot_clips(ASSETS)
    settings = AudioCoexistenceSettings("USB Audio Device")
    schedule = build_audio_coexistence_plan(120.645, clips, settings)
    assert [trial.stimulus_id for trial in schedule] == [
        "beep", "buzz", "white_noise", "beep", "buzz", "white_noise", "beep", "buzz",
    ]
    assert [trial.planned_offset_s for trial in schedule] == list(range(10, 116, 15))
    assert all(clips[trial.stimulus_id].duration_s == 3.0 for trial in schedule)
    assert all(
        later.planned_offset_s >= earlier.planned_offset_s + 3.0
        for earlier, later in pairwise(schedule)
    )
    assert build_audio_coexistence_plan(12.9, clips, settings) == ()


def test_coexistence_fake_playback_logs_request_callback_and_end(tmp_path):
    clips = load_pilot_clips(ASSETS)
    settings = AudioCoexistenceSettings("USB Audio Device", start_delay_s=0, interval_s=3)
    schedule = build_audio_coexistence_plan(9, clips, settings)
    audio = FakeAudio()
    audio.prepare(clips, settings.gains_db)
    session_id = "audio-coexistence-test"
    events = UnifiedEventStream(
        tmp_path / "events.jsonl", session_id=session_id, clock=SessionClock.start(session_id)
    )
    latencies = []
    requests = []
    errors = []
    _play_coexistence_audio(
        audio, schedule, events, events.clock,
        time.monotonic_ns() - 10_000_000_000, threading.Event(), latencies, requests, errors,
    )
    diagnostics = events.close()
    records = [
        json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert diagnostics["dropped_count"] == diagnostics["error_count"] == 0
    assert audio.played == [trial.stimulus_id for trial in schedule]
    assert requests == [1, 2, 3] and len(latencies) == 3 and not errors
    assert [record["event"] for record in records] == [
        "AUDIO_TRIAL_START", "AUDIO_REQUEST", "AUDIO_CALLBACK_START", "AUDIO_TRIAL_END",
    ] * 3
    callback = next(record for record in records if record["event"] == "AUDIO_CALLBACK_START")
    assert callback["callback_semantics"] == "PCM callback start; not physical acoustic onset"
    assert callback["monotonic_ns"] > 0 and callback["utc_ns"] > 0


def test_assets_preload_and_fake_session(tmp_path):
    clips = load_pilot_clips(ASSETS)
    assert set(clips) == {"beep", "buzz", "white_noise"}
    assert all(clip.duration_s == 3.0 and len(clip.pcm) == 288_000 for clip in clips.values())
    config = load_config(PROFILE)
    config = replace(config, paths=replace(config.paths, output_root=tmp_path))
    settings = AudioPilotSettings.from_config(config)
    audio = FakeAudio()
    result = run_audio_pilot(config, settings, audio, session_id="pilot-test", sleep=lambda _: None)
    assert result["status"] == "COMPLETE"
    assert result["requested_sounds"] == result["callback_starts"] == 30
    assert result["missed_requests"] == result["callback_status_errors"] == 0
    assert audio.played == [trial.stimulus_id for trial in build_plan(settings)]
    assert audio.closed
    session_root = tmp_path / "pilot-test"
    events = [json.loads(line) for line in (session_root / "events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events[:5]] == [
        "CLOCK_SYNC", "AUDIO_TRIAL_START", "AUDIO_REQUEST", "AUDIO_CALLBACK_START",
        "AUDIO_TRIAL_END",
    ]
    assert [event["event"] for event in events].count("AUDIO_CALLBACK_START") == 30
    request = events[2]
    assert request["trial_index"] == 1
    assert request["stimulus_id"] == audio.played[0]
    assert request["filename"] == clips[audio.played[0]].filename
    assert request["monotonic_ns"] > 0 and request["utc_ns"] > 0
    manifest = json.loads((session_root / "audio_manifest.json").read_text())
    assert manifest["random_seed"] == settings.seed
    assert {item["sha256"] for item in manifest["stimuli"]} == {
        clip.sha256 for clip in clips.values()
    }
    assert all(item["gain_db"] == 0 for item in manifest["stimuli"])
    assert all((session_root / "audio" / clip.filename).read_bytes() ==
               (ASSETS / clip.filename).read_bytes() for clip in clips.values())
    assert json.loads((session_root / "final_status.json").read_text())["status"] == "COMPLETE"
    assert json.loads((session_root / "resolved_config.json").read_text())["session"]["simulation"] is False


@pytest.mark.parametrize("devices,match", [
    ([{"name": "HDMI", "max_output_channels": 2}], "USB Audio Device"),
    ([{"name": "USB Audio Device A", "max_output_channels": 2},
      {"name": "USB Audio Device B", "max_output_channels": 2}], "USB Audio Device"),
])
def test_missing_or_ambiguous_device_fails(devices, match):
    with pytest.raises(AudioError, match="expected exactly one"):
        select_output_device(devices, match)
    assert select_output_device([{"name": "HDMI", "max_output_channels": 2},
                                 {"name": "USB Audio Device", "max_output_channels": 2}],
                                "USB Audio Device") == 1


def test_playback_failure_finalizes_and_closes(tmp_path):
    class FailingAudio(FakeAudio):
        def play(self, stimulus_id):
            raise AudioError("injected playback failure")

    config = load_config(PROFILE)
    config = replace(config, paths=replace(config.paths, output_root=tmp_path))
    audio = FailingAudio()
    with pytest.raises(AudioError, match="injected playback failure"):
        run_audio_pilot(config, AudioPilotSettings.from_config(config), audio,
                        session_id="failed", sleep=lambda _: None)
    assert audio.closed
    assert json.loads((tmp_path / "failed/final_status.json").read_text())["status"] == "FAILED"


def test_cli_simulation_smoke(tmp_path, capsys):
    from rpi_vstim.cli import main

    assert main(["audio-pilot", "--config", str(PROFILE), "--simulate", "--smoke",
                 "--output-root", str(tmp_path), "--session-id", "smoke", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["requested_sounds"] == 6
    assert json.loads((tmp_path / "smoke/resolved_config.json").read_text())["session"]["simulation"] is True


def test_persistent_stream_and_callback_status_without_hardware(monkeypatch):
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.closed = False

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            self.closed = True

    class SoundDevice:
        def __init__(self):
            self.streams = []

        def query_devices(self):
            return [{"name": "HDMI", "max_output_channels": 2},
                    {"name": "USB Audio Device", "max_output_channels": 2}]

        def RawOutputStream(self, **kwargs):
            stream = Stream(**kwargs)
            self.streams.append(stream)
            return stream

    module = SoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    audio = SoundDeviceAudio("USB Audio Device")
    clip = load_pilot_clips(ASSETS)["beep"]
    audio.prepare({"beep": clip}, {"beep": 0.0})
    assert audio._pcm["beep"] == clip.pcm

    for bad_status in (False, True):
        result = []
        thread = threading.Thread(target=lambda result=result: result.append(audio.play("beep")))
        thread.start()
        deadline = time.monotonic() + 1
        while audio._active is None and time.monotonic() < deadline:
            time.sleep(0.001)
        assert audio._active is not None
        module.streams[0].callback(bytearray(len(clip.pcm)), clip.frames, None, bad_status)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert result[0].callback_monotonic_ns > 0
        assert result[0].status_errors == int(bad_status)

    assert len(module.streams) == 1
    assert audio.diagnostics() == {
        "requested_sounds": 2, "callback_starts": 2,
        "missed_requests": 0, "callback_status_errors": 1,
    }
    audio.close()
    assert module.streams[0].closed
    with pytest.raises(AudioError, match="gain clips"):
        SoundDeviceAudio("USB Audio Device").prepare({"beep": clip}, {"beep": 20.0})
    assert len(module.streams) == 1
