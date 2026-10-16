"""Small persistent-stream audio output API for preloaded mono PCM WAVs."""

from __future__ import annotations

import csv
import hashlib
import math
import sys
import threading
import time
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class AudioError(RuntimeError):
    """Audio preparation, device selection, or playback failed."""


@dataclass(frozen=True)
class AudioClip:
    stimulus_id: str
    filename: str
    sha256: str
    pcm: bytes
    sample_rate_hz: int
    frames: int

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate_hz


@dataclass(frozen=True)
class PlaybackResult:
    callback_monotonic_ns: int
    callback_utc_ns: int
    status_errors: int = 0
    error: str = ""


class AudioOutput(Protocol):
    def prepare(self, clips: dict[str, AudioClip], gains_db: dict[str, float]) -> None: ...
    def play(self, stimulus_id: str) -> PlaybackResult: ...
    def close(self) -> None: ...
    def diagnostics(self) -> dict[str, int]: ...


def load_pilot_clips(root: Path) -> dict[str, AudioClip]:
    """Verify the committed manifest and preload every WAV before a trial starts."""
    with (root / "manifest.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if {row["stimulus_id"] for row in rows} != {"beep", "buzz", "white_noise"} or len(rows) != 3:
        raise AudioError("pilot manifest must contain exactly beep, buzz, and white_noise")
    expected_files = {
        "beep": "beep_1khz_3s.wav",
        "buzz": "buzz_200hz_harmonic_3s.wav",
        "white_noise": "white_noise_3s.wav",
    }
    clips = {}
    for row in rows:
        filename = row["filename"]
        if filename != expected_files[row["stimulus_id"]]:
            raise AudioError(f"invalid pilot filename: {filename}")
        path = root / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            raise AudioError(f"SHA256 mismatch for {filename}")
        with wave.open(str(path), "rb") as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth(),
                source.getnframes(), source.getcomptype()) != (48_000, 1, 2, 144_000, "NONE"):
                raise AudioError(f"unsupported pilot WAV format: {filename}")
            pcm = source.readframes(source.getnframes())
        clips[row["stimulus_id"]] = AudioClip(
            row["stimulus_id"], filename, digest, pcm, 48_000, 144_000
        )
    return clips


def select_output_device(devices: list[dict], name_match: str) -> int:
    if not name_match.strip():
        raise AudioError("audio output device_name_match is required")
    matches = [index for index, device in enumerate(devices)
               if int(device.get("max_output_channels", 0)) >= 1
               and name_match.casefold() in str(device.get("name", "")).casefold()]
    if len(matches) != 1:
        raise AudioError(
            f"audio output device match {name_match!r} found {len(matches)} devices; expected exactly one"
        )
    return matches[0]


@dataclass
class _Playback:
    pcm: bytes
    done: threading.Event = field(default_factory=threading.Event)
    offset: int = 0
    callback_monotonic_ns: int = 0
    callback_utc_ns: int = 0
    status_errors: int = 0
    error: str = ""


class SoundDeviceAudio:
    """One PortAudio output stream; callbacks copy only preloaded PCM bytes."""

    def __init__(self, device_name_match: str) -> None:
        self.device_name_match = device_name_match
        self._stream = None
        self._pcm: dict[str, bytes] = {}
        self._active: _Playback | None = None
        self._requested = 0
        self._callback_starts = 0
        self._missed = 0
        self._status_errors = 0

    def prepare(self, clips: dict[str, AudioClip], gains_db: dict[str, float]) -> None:
        if self._stream is not None:
            raise AudioError("audio stream is already prepared")
        if set(clips) != set(gains_db):
            raise AudioError("each audio clip needs one configured gain")
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise AudioError("install the optional audio dependencies and PortAudio") from exc
        try:
            device = select_output_device(list(sd.query_devices()), self.device_name_match)
        except AudioError:
            raise
        except Exception as exc:
            raise AudioError(f"audio device discovery failed: {exc}") from exc
        pcm = {}
        for stimulus_id, clip in clips.items():
            samples = array("h")
            samples.frombytes(clip.pcm)
            if sys.byteorder == "big":
                samples.byteswap()
            try:
                scale = 10 ** (gains_db[stimulus_id] / 20)
            except OverflowError as exc:
                raise AudioError(f"invalid gain for {stimulus_id}") from exc
            if not math.isfinite(scale):
                raise AudioError(f"invalid gain for {stimulus_id}")
            adjusted = array("h")
            for sample in samples:
                value = round(sample * scale)
                if not -32768 <= value <= 32767:
                    raise AudioError(f"gain clips {stimulus_id}; lower gain_db")
                adjusted.append(value)
            if sys.byteorder == "big":
                adjusted.byteswap()
            pcm[stimulus_id] = adjusted.tobytes()
        stream = None
        try:
            stream = sd.RawOutputStream(
                samplerate=48_000, channels=1, dtype="int16", device=device,
                callback=self._callback
            )
            stream.start()
        except Exception as exc:
            if stream is not None:
                stream.close()
            raise AudioError(f"audio stream could not start: {exc}") from exc
        self._pcm = pcm
        self._stream = stream

    def _callback(self, outdata, frames: int, _time, status) -> None:
        playback = self._active
        try:
            outdata[:] = bytes(frames * 2)
            if status:
                self._status_errors += 1
                if playback is not None:
                    playback.status_errors += 1
            if playback is None or playback.done.is_set():
                return
            if playback.callback_monotonic_ns == 0:
                playback.callback_monotonic_ns = time.monotonic_ns()
                playback.callback_utc_ns = time.time_ns()
                self._callback_starts += 1
            count = min(frames * 2, len(playback.pcm) - playback.offset)
            outdata[:count] = playback.pcm[playback.offset:playback.offset + count]
            playback.offset += count
            if playback.offset == len(playback.pcm):
                playback.done.set()
        except Exception as exc:  # noqa: BLE001 - callback failures must reach the main thread.
            if playback is not None:
                playback.error = str(exc)
                playback.done.set()

    def play(self, stimulus_id: str) -> PlaybackResult:
        if self._stream is None or stimulus_id not in self._pcm:
            raise AudioError(f"audio clip is not prepared: {stimulus_id}")
        if self._active is not None:
            raise AudioError("audio playback is already active")
        self._requested += 1
        playback = _Playback(self._pcm[stimulus_id])
        self._active = playback
        try:
            if not playback.done.wait(len(playback.pcm) / (48_000 * 2) + 5):
                self._missed += 1
                raise AudioError(f"audio callback timed out for {stimulus_id}")
            if playback.callback_monotonic_ns == 0:
                self._missed += 1
            return PlaybackResult(
                playback.callback_monotonic_ns,
                playback.callback_utc_ns,
                playback.status_errors,
                playback.error,
            )
        finally:
            self._active = None

    def diagnostics(self) -> dict[str, int]:
        return {
            "requested_sounds": self._requested,
            "callback_starts": self._callback_starts,
            "missed_requests": self._missed,
            "callback_status_errors": self._status_errors,
        }

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()


class FakeAudio:
    """Hardware-free playback for protocol tests and simulated runs."""

    def __init__(self) -> None:
        self.prepared: dict[str, AudioClip] = {}
        self.played: list[str] = []
        self.closed = False

    def prepare(self, clips: dict[str, AudioClip], gains_db: dict[str, float]) -> None:
        if set(clips) != set(gains_db):
            raise AudioError("each audio clip needs one configured gain")
        self.prepared = dict(clips)

    def play(self, stimulus_id: str) -> PlaybackResult:
        if stimulus_id not in self.prepared:
            raise AudioError(f"audio clip is not prepared: {stimulus_id}")
        self.played.append(stimulus_id)
        return PlaybackResult(time.monotonic_ns(), time.time_ns())

    def diagnostics(self) -> dict[str, int]:
        return {
            "requested_sounds": len(self.played),
            "callback_starts": len(self.played),
            "missed_requests": 0,
            "callback_status_errors": 0,
        }

    def close(self) -> None:
        self.closed = True
