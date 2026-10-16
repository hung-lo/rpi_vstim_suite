"""Hardware-free checks for the committed pilot audio assets."""

import csv
import hashlib
import importlib.util
import math
import sys
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets/audio/pilot"
FILENAMES = {
    "beep_1khz_3s.wav",
    "buzz_200hz_harmonic_3s.wav",
    "white_noise_3s.wav",
}


def test_pilot_wavs_and_manifest():
    with (ASSETS / "manifest.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 3
    assert {row["filename"] for row in rows} == FILENAMES
    assert {row["stimulus_id"] for row in rows} == {"beep", "buzz", "white_noise"}
    assert {path.name for path in ASSETS.glob("*.wav")} == FILENAMES

    measured = []
    for row in rows:
        path = ASSETS / row["filename"]
        assert path.is_file()
        with wave.open(str(path), "rb") as source:
            assert source.getframerate() == int(row["sample_rate_hz"]) == 48_000
            assert source.getnchannels() == int(row["channels"]) == 1
            assert source.getsampwidth() * 8 == int(row["pcm_bits"]) == 16
            assert source.getcomptype() == "NONE"
            assert source.getnframes() == 144_000
            assert source.getnframes() / source.getframerate() == float(row["duration_s"]) == 3.0
            samples = array("h")
            samples.frombytes(source.readframes(source.getnframes()))
            if sys.byteorder == "big":
                samples.byteswap()
        assert samples[0] == samples[-1] == 0
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        peak = max(abs(sample) for sample in samples) / 32768
        assert abs(rms - float(row["measured_rms"])) < 1e-8
        assert abs(peak - float(row["peak"])) < 1e-8
        assert abs(rms - float(row["target_rms"])) < 1e-4
        assert int(row["fade_ms"]) == 10
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        measured.append(rms)
    assert max(measured) - min(measured) < 1e-4


def test_pilot_regeneration_is_byte_identical(tmp_path):
    spec = importlib.util.spec_from_file_location("generate_pilot_audio", ROOT / "tools/generate_pilot_audio.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.generate(tmp_path)
    for name in FILENAMES | {"manifest.csv"}:
        assert (tmp_path / name).read_bytes() == (ASSETS / name).read_bytes()
