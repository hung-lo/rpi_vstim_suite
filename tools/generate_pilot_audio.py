"""Generate deterministic, equal-digital-RMS pilot WAV stimuli."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
import sys
import wave
from array import array
from pathlib import Path

SAMPLE_RATE_HZ = 48_000
DURATION_S = 3
FRAME_COUNT = SAMPLE_RATE_HZ * DURATION_S
FADE_MS = 10
FADE_FRAMES = SAMPLE_RATE_HZ * FADE_MS // 1000
TARGET_RMS = 0.18
NOISE_SEED = 20261015
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "assets/audio/pilot"

STIMULI = (
    ("beep", "beep_1khz_3s.wav", "1 kHz sine tone"),
    ("buzz", "buzz_200hz_harmonic_3s.wav", "200 Hz harmonic-complex buzz"),
    ("white_noise", "white_noise_3s.wav", "Broadband white noise"),
)
FIELDS = (
    "stimulus_id", "filename", "description", "sample_rate_hz", "duration_s",
    "channels", "pcm_bits", "target_rms", "measured_rms", "peak", "fade_ms", "sha256",
)


def _samples(stimulus_id: str) -> list[float]:
    if stimulus_id == "white_noise":
        rng = random.Random(NOISE_SEED)
        values = [rng.uniform(-1.0, 1.0) for _ in range(FRAME_COUNT)]
    elif stimulus_id == "beep":
        values = [math.sin(2 * math.pi * 1000 * i / SAMPLE_RATE_HZ) for i in range(FRAME_COUNT)]
    else:
        harmonics = ((200, 1.00), (400, 0.55), (600, 0.35), (800, 0.22), (1000, 0.15))
        values = [
            sum(amplitude * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE_HZ)
                for frequency, amplitude in harmonics)
            for i in range(FRAME_COUNT)
        ]

    for i in range(FADE_FRAMES):
        gain = 0.5 * (1 - math.cos(math.pi * i / (FADE_FRAMES - 1)))
        values[i] *= gain
        values[-i - 1] *= gain

    rms = math.sqrt(sum(value * value for value in values) / FRAME_COUNT)
    scale = TARGET_RMS / rms
    return [value * scale for value in values]


def generate(output_dir: Path = DEFAULT_OUTPUT) -> list[dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for stimulus_id, filename, description in STIMULI:
        values = _samples(stimulus_id)
        pcm = array("h", (round(value * 32768) for value in values))
        if max(abs(sample) for sample in pcm) > 32767:
            raise ValueError(f"{filename} would clip")
        measured_rms = math.sqrt(sum(sample * sample for sample in pcm) / FRAME_COUNT) / 32768
        peak = max(abs(sample) for sample in pcm) / 32768
        if sys.byteorder == "big":
            pcm.byteswap()
        path = output_dir / filename
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, SAMPLE_RATE_HZ, FRAME_COUNT, "NONE", "not compressed"))
            output.writeframes(pcm.tobytes())
        rows.append({
            "stimulus_id": stimulus_id,
            "filename": filename,
            "description": description,
            "sample_rate_hz": str(SAMPLE_RATE_HZ),
            "duration_s": f"{DURATION_S:.3f}",
            "channels": "1",
            "pcm_bits": "16",
            "target_rms": f"{TARGET_RMS:.6f}",
            "measured_rms": f"{measured_rms:.8f}",
            "peak": f"{peak:.8f}",
            "fade_ms": str(FADE_MS),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    with (output_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    generate(parser.parse_args().output_dir)
