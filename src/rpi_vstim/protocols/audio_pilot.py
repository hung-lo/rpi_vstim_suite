"""Deterministic, audio-only engineering pilot using the committed WAV set."""

from __future__ import annotations

import json
import math
import random
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rpi_vstim.audio import AudioError, AudioOutput, load_pilot_clips
from rpi_vstim.core.config import Config
from rpi_vstim.core.session import atomic_write_json, new_session
from rpi_vstim.events import SessionClock, UnifiedEventStream

ASSET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/pilot"
STIMULUS_IDS = ("beep", "buzz", "white_noise")


@dataclass(frozen=True)
class AudioPilotSettings:
    device_name_match: str = ""
    repeats_per_stimulus: int = 10
    seed: int = 20261015
    iti_min_s: float = 1.0
    iti_max_s: float = 2.0
    initial_silence_s: float = 3.0
    final_silence_s: float = 3.0
    gains_db: dict[str, float] = field(default_factory=lambda: {
        stimulus_id: 0.0 for stimulus_id in STIMULUS_IDS
    })

    @classmethod
    def from_config(cls, config: Config) -> AudioPilotSettings:
        parameters = dict(config.protocol.parameters)
        unknown = set(parameters) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown audio pilot setting(s): {', '.join(sorted(unknown))}")
        settings = cls(**parameters)
        gains = settings.gains_db
        if not isinstance(settings.device_name_match, str):
            raise TypeError("device_name_match must be a string")
        if not isinstance(gains, dict):
            raise TypeError("gains_db must be a table")
        if set(gains) != set(STIMULUS_IDS):
            raise ValueError("gains_db must specify beep, buzz, and white_noise")
        if (type(settings.repeats_per_stimulus) is not int or settings.repeats_per_stimulus < 1
            or type(settings.seed) is not int):
            raise ValueError("repeats_per_stimulus must be positive and seed must be an integer")
        durations = (settings.iti_min_s, settings.iti_max_s,
                     settings.initial_silence_s, settings.final_silence_s)
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
               for value in durations) or settings.iti_min_s > settings.iti_max_s:
            raise ValueError("audio pilot ITI and silence durations must be finite and non-negative")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in gains.values()):
            raise ValueError("audio gains_db values must be finite numbers")
        return cls(**{**asdict(settings), "gains_db": dict(gains)})


@dataclass(frozen=True)
class AudioTrial:
    trial_index: int
    stimulus_id: str
    iti_after_s: float


def build_plan(settings: AudioPilotSettings) -> tuple[AudioTrial, ...]:
    rng = random.Random(settings.seed)
    order = list(STIMULUS_IDS) * settings.repeats_per_stimulus
    rng.shuffle(order)
    return tuple(
        AudioTrial(index, stimulus_id, rng.uniform(settings.iti_min_s, settings.iti_max_s)
                   if index < len(order) else 0.0)
        for index, stimulus_id in enumerate(order, 1)
    )


def run_audio_pilot(
    config: Config,
    settings: AudioPilotSettings,
    audio: AudioOutput,
    *,
    session_id: str,
    asset_root: Path = ASSET_ROOT,
    sleep: Callable[[float], None] = time.sleep,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> dict[str, object]:
    clips = load_pilot_clips(asset_root)
    plan = build_plan(settings)
    session = new_session(config, protocol_name="audio-pilot", session_id=session_id,
                          seed=settings.seed)
    session.write_initial_outputs()
    clock = SessionClock.start(session_id)
    events = None
    latencies_ms: list[float] = []
    failure: BaseException | None = None
    cleanup_errors: list[str] = []
    diagnostics: dict[str, int] = {}
    try:
        session.write_plan({
            "protocol": "audio-pilot", "seed": settings.seed,
            "initial_silence_s": settings.initial_silence_s,
            "final_silence_s": settings.final_silence_s,
            "trials": [{**asdict(trial), "filename": clips[trial.stimulus_id].filename,
                        "duration_s": clips[trial.stimulus_id].duration_s}
                       for trial in plan],
        })
        audio_dir = session.context.session_root / "audio"
        audio_dir.mkdir()
        for clip in clips.values():
            shutil.copyfile(asset_root / clip.filename, audio_dir / clip.filename)
        atomic_write_json(session.context.session_root / "audio_manifest.json", {
            "random_seed": settings.seed,
            "device_name_match": settings.device_name_match,
            "stimuli": [
                {"stimulus_id": clip.stimulus_id, "filename": clip.filename,
                 "sha256": clip.sha256, "sample_rate_hz": clip.sample_rate_hz,
                 "duration_s": clip.duration_s, "gain_db": settings.gains_db[clip.stimulus_id]}
                for clip in clips.values()
            ],
        })
        events = UnifiedEventStream(session.context.session_root / "events.jsonl",
                                    session_id=session_id, clock=clock)

        def emit(name: str, timestamp_ns: int, trial: AudioTrial | None = None, **detail) -> None:
            fields = {"trial_index": trial.trial_index, "stimulus_id": trial.stimulus_id,
                      "filename": clips[trial.stimulus_id].filename} if trial else {}
            fields.update(detail)
            events.emit_reliable(name, source_monotonic_ns=timestamp_ns, **fields)
            session.record_event(name, sequence_id=str(trial.trial_index) if trial else "",
                                 detail=json.dumps({"monotonic_ns": timestamp_ns, **fields},
                                                   sort_keys=True))

        emit("CLOCK_SYNC", monotonic_ns(), **clock.sync_fields())
        audio.prepare(clips, settings.gains_db)
        deadline_ns = monotonic_ns() + round(settings.initial_silence_s * 1e9)
        for trial in plan:
            sleep(max(0.0, (deadline_ns - monotonic_ns()) / 1e9))
            trial_start_ns = monotonic_ns()
            emit("AUDIO_TRIAL_START", trial_start_ns, trial, planned_request_monotonic_ns=deadline_ns,
                 planned_request_utc_ns=clock.fields(deadline_ns)["utc_ns"])
            request_ns = monotonic_ns()
            try:
                result = audio.play(trial.stimulus_id)
            except BaseException:  # Report the attempted trial before propagating playback/Ctrl-C.
                emit("AUDIO_REQUEST", request_ns, trial)
                emit("AUDIO_TRIAL_END", monotonic_ns(), trial, error="playback interrupted")
                raise
            emit("AUDIO_REQUEST", request_ns, trial)
            if result.callback_monotonic_ns:
                latency_ms = (result.callback_monotonic_ns - request_ns) / 1e6
                latencies_ms.append(latency_ms)
                emit("AUDIO_CALLBACK_START", result.callback_monotonic_ns, trial,
                     callback_utc_ns=result.callback_utc_ns,
                     request_to_callback_ms=latency_ms)
            emit("AUDIO_TRIAL_END", monotonic_ns(), trial, callback_status_errors=result.status_errors)
            if result.error or result.status_errors or not result.callback_monotonic_ns:
                raise AudioError(result.error or f"audio callback failed for {trial.stimulus_id}")
            deadline_ns += round((clips[trial.stimulus_id].duration_s + trial.iti_after_s) * 1e9)
        sleep(settings.final_silence_s)
        diagnostics = audio.diagnostics()
        if diagnostics["missed_requests"] or diagnostics["callback_status_errors"]:
            raise AudioError(f"audio playback diagnostics failed: {diagnostics}")
    except BaseException as exc:  # noqa: BLE001 - record Ctrl-C as ABORTED before re-raising.
        failure = exc
    finally:
        try:
            audio.close()
        except Exception as exc:  # noqa: BLE001 - preserve cleanup failures in final status.
            cleanup_errors.append(f"audio close: {exc}")
        if events is not None:
            try:
                diagnostics = audio.diagnostics()
                events.emit_reliable("AUDIO_SUMMARY", **diagnostics,
                                     request_to_callback_latency_ms=latencies_ms)
                event_diagnostics = events.close()
                if event_diagnostics["dropped_count"] or event_diagnostics["error_count"]:
                    cleanup_errors.append(f"event writer: {event_diagnostics}")
            except Exception as exc:  # noqa: BLE001 - preserve writer failures in final status.
                cleanup_errors.append(f"event writer close: {exc}")
        atomic_write_json(session.context.session_root / "audio_summary.json", {
            **diagnostics, "request_to_callback_latency_ms": latencies_ms,
        })
        status = "ABORTED" if isinstance(failure, KeyboardInterrupt) else "FAILED" if failure else "COMPLETE"
        if cleanup_errors:
            status = "CLEANUP_FAILED"
        session.update_status(status, lifecycle=status,
                              error=str(failure) if failure else None,
                              cleanup_errors=cleanup_errors or None)
        session.close()
    if failure is not None:
        raise failure
    if cleanup_errors:
        raise AudioError("; ".join(cleanup_errors))
    return {"session_root": str(session.context.session_root), "status": "COMPLETE",
            **diagnostics, "request_to_callback_latency_ms": latencies_ms}
