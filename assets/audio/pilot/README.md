# Three-second pilot audio stimuli

These three engineering stimuli preserve the current Go/NoGo sound presentation
duration of 3 seconds for upcoming USB-audio integration tests. They are not
animal-facing stimuli with calibrated loudness or sound pressure level (SPL).

All files are 48 kHz mono signed 16-bit PCM WAV, exactly 3.000 seconds long,
with 10 ms raised-cosine onset and offset fades. Each waveform is normalized
independently to a target digital RMS of 0.18 before PCM conversion. The
manifest records RMS and peak measured from the committed PCM, plus its SHA256.
Equal digital RMS does not guarantee equal perceived loudness across spectra;
final animal-facing SPL and loudness calibration is still required.

The beep is a 1 kHz sine. The buzz sums 200, 400, 600, 800, and 1000 Hz
harmonics with amplitudes 1.00, 0.55, 0.35, 0.22, and 0.15. White noise uses
independent uniform samples from Python's deterministic RNG with seed 20261015.
No perceptual weighting is applied.

Regenerate from the repository root:

```bash
python tools/generate_pilot_audio.py
```

Use `--output-dir /tmp/pilot-audio` to generate a comparison copy. This asset
set does not add an audio playback backend or require audio hardware.
