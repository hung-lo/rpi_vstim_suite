# Audio-only engineering pilot

This pilot plays the three committed [3-second WAVs](../assets/audio/pilot/README.md)
through one persistent 48 kHz PortAudio output stream. It preloads every WAV
before trials, applies configured per-stimulus gains in memory, and never opens
the device per trial. It does not use the display, cameras, or GPIO.

Install the optional Python backend on the Pi with the repository's normal
Python 3.13 environment:

```bash
python -m pip install --no-build-isolation -e '.[audio]'
```

The system must also provide PortAudio (`libportaudio2` on Debian). The
default [Pi 5 example profile](../config/rigs/pi5_audio_pilot.example.toml)
selects one output device whose name contains `USB Audio Device`. If zero or
multiple output devices match, the run fails rather than using a default
device. Inspect available devices with `python -m sounddevice`; set
`device_name_match` to a unique substring for the intended USB adapter.
The observed C-Media/Unitek adapter appeared as ALSA `hw:2,0` during one
test, but card numbers can change.

## Run

First run six fake trials without audio hardware:

```bash
rpi-vstim audio-pilot --simulate --smoke --config config/rigs/pi5_audio_pilot.example.toml --output-root /tmp/rpi-vstim-audio-sessions
```

Short Pi hardware smoke test (six 3-second sounds, five 1–2 second ITIs,
plus 3-second initial and final silence):

```bash
rpi-vstim audio-pilot --smoke --config config/rigs/pi5_audio_pilot.example.toml --output-root /mnt/behavbox_ssd/sessions
```

The full pilot omits `--smoke`: 10 presentations each of beep, buzz, and white
noise in seed-determined random order, 30 trials total. `--seed N` overrides
the profile seed. The profile also sets ITI bounds, initial/final silence,
and `gains_db` for each stimulus. The current gains are all 0 dB. Final
animal-facing gain and sound pressure level (SPL) must be calibrated with
measurements at the mouse position. Equal digital RMS does not imply equal
perceived loudness.

## Session output and timing

The run creates a normal session with `plan.json`, `events.csv`,
`events.jsonl`, `final_status.json`, copied WAVs in `audio/`,
`audio_manifest.json`, and `audio_summary.json`. The audio manifest records
IDs, filenames, SHA256, rate, duration, gain, and seed. The summary records
requests, callback starts, missed requests, callback status errors, and each
request-to-callback latency.

`CLOCK_SYNC` maps `CLOCK_MONOTONIC` events to UTC. `AUDIO_TRIAL_START` records
the planned request time; `AUDIO_REQUEST` records the actual request;
`AUDIO_CALLBACK_START` is when the PortAudio callback first consumes PCM.
`AUDIO_TRIAL_END` records handoff completion. These timestamps are software
observations, not physical acoustic onset. Absolute command-to-speaker
latency and full-stack coexistence remain unmeasured. A callback status
error, timeout, or playback exception marks the session failed and closes
the stream; Ctrl-C marks it aborted.

## Same-session visual/audio coexistence

The natural-image runner has an opt-in validation mode that keeps KMS, both
cameras, events, and USB audio in one session. It reuses the natural-image
profile's visual timing and the audio profile's unique device-name match and
gains. With the current visual profile, `--image-count 84 --seed 0` plans about
120.6 seconds. The fixed audio order starts 10 seconds after KMS sequence
dispatch and repeats beep, buzz, and white noise every 15 seconds; this plans
eight non-overlapping sounds.

```bash
rpi-vstim natural-images run \
  --mouse-id <id> \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --image-count 84 --seed 0 --cameras \
  --audio-coexistence \
  --audio-config config/rigs/pi5_audio_pilot.example.toml \
  --output-root /mnt/behavbox_ssd/sessions
```

The session adds `audio/` copies of the stimuli and manifest,
`audio_plan.json`, `audio_manifest.json`, and `audio_summary.json`. The audio
events share the session's monotonic/UTC mapping. Callback timestamps indicate
when the software output callback starts consuming PCM, not acoustic onset.
This mode is for coexistence validation; it does not establish audiovisual
synchronization or animal-facing loudness calibration.
