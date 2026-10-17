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
latency remains unmeasured. Full-stack coexistence passed a short Pi 5 run;
see the [validation record](hardware/pi5_av_coexistence_2026-10-16.md). A
callback status error, timeout, or playback exception marks the session failed
and closes the stream; Ctrl-C marks it aborted.

## Same-session visual/audio coexistence

The natural-image runner has an opt-in mode that keeps KMS, both cameras,
events, and USB audio in one session. It reuses the natural-image profile's
visual timing and the audio profile's unique device-name match and gains. The
natural-image profile's `[protocol.parameters.audio_coexistence]` table sets
the ordered `sequence`, `start_delay_s`, and `interval_s`. The provided example
cycles beep, buzz, and white noise every 15 seconds beginning at 10 seconds.
For example:

```toml
[protocol.parameters.audio_coexistence]
sequence = ["beep", "buzz", "white_noise"]
start_delay_s = 10.0
interval_s = 15.0
```

`--image-count 84 --seed 0` produces a 120.645-second visual plan and eight
non-overlapping sounds; the audio schedule stops at the end of that plan.
The audio order is fixed by the sequence; `--seed` controls the visual image
plan, and the visual plan length determines the session duration.

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
The full stack passed a ~2-minute run with all eight requests receiving
callbacks and no event drops, writer errors, or KMS missed vblanks. See the
[recorded results](hardware/pi5_av_coexistence_2026-10-16.md). This is an
integration/coexistence validation, not a long-duration audio endurance test;
it does not establish audiovisual synchronization, acoustic onset, or
animal-facing loudness calibration. The real natural-image path requires Pi
KMS and is not available as a user-facing `--simulate` run; `audio-pilot
--simulate` remains available for hardware-free audio protocol testing.
