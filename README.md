# rpi_vstim_suite

An internal lab prototype for Raspberry Pi 5 visual stimulation and behavioral
experiments. It combines direct KMS presentation, local cameras, GPIO inputs
and outputs, event/timing logs, NVMe session storage, and reusable protocol
code. An optional persistent USB-audio backend and engineering pilot are also
included.

**Status: v0.1 internal lab prototype / research software.** This is not production
certification, and not every protocol or behavioral apparatus is validated.

## Supported platform

Raspberry Pi 5 with Debian 13/Trixie and Python `>=3.13,<3.14` is the validated
hardware target. Simulation and development are available on other machines
with a supported Python runtime; those machines do not provide Pi hardware
capabilities.

## Validation status

| Area | Status |
|---|---|
| Pi 5 KMS visual presentation and natural-image demo | Validated; use recorded kernel/KMS timestamps for analysis |
| Dual local camera recording, preview, shutdown, fast QC | Validated on the Pi 5 |
| Session event logging and direct NVMe recording | Validated, including integrated sessions with zero event drops/errors |
| Python 3.13 runtime | Validated on the Pi 5; project target is `<3.14` |
| Lick inputs | BCM26/27 electrically tested; BCM15 center input is not connected/validated |
| Reward and vacuum GPIO path | GPIO/software line checks performed; complete fluidics and animal calibration remain apparatus work |
| Chrony and external NeuroKairos IRIG-H | Validated as optional system services; VStim does not control them |
| Optical IRIG recovery | Validated separately; downstream acquisition-device timing remains pending |
| USB audio by itself | Standalone playback characterized; pilot software and a six-trial smoke are available |
| USB audio pilot protocol | Persistent USB playback with preloaded stimuli and session timing/events |
| USB audio with the full VStim stack | **Validated** in a ~2-minute Pi 5 coexistence run; [session record](docs/hardware/pi5_av_coexistence_2026-10-16.md) |

Still pending are final animal-facing water calibration, audio SPL calibration
at the mouse position, physical acoustic-onset calibration, photodiode
visual-onset calibration, and downstream acquisition-device IRIG validation.
Drifting-grating and retinotopy planners and compatibility wrappers exist, but
they have not been migrated to or validated through the current Pi KMS display
runner. See [the Pi 5 deployment notes](docs/pi5_rig.md) and
[hardware records](docs/hardware/).

## Current Pi 5 rig

```text
Pi 5
├── HDMI/KMS stimulus screen and operator display
├── CSI camera 1 and CSI camera 2
├── NVMe session storage
├── GPIO behavioral I/O
├── USB audio adapter → 3.5 mm analog output → speaker
└── BCM GPIO9 → external NeuroKairos IRIG-H (reserved; VStim never acquires it)
```

The current rig is not Box151. BCM GPIO23 and GPIO24 are currently unassigned;
they are not audio triggers. NeuroKairos is an optional external service.

## Quick start

On the Pi, install system dependencies separately from Python packages. The
camera workflow uses Raspberry Pi `rpicam-*` tools and `ffprobe`; GPIO uses the
system `lgpio` binding; native KMS needs a C compiler and libdrm development
files. USB audio additionally needs PortAudio (Debian package `libportaudio2`)
and the optional Python `sounddevice` extra. See
[getting started](docs/getting_started.md); no full OS upgrade is part of setup.

```bash
git clone https://github.com/hung-lo/rpi_vstim_suite.git
cd rpi_vstim_suite
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-build-isolation -e .
# Only needed for USB audio:
python -m pip install --no-build-isolation -e '.[audio]'
```

Check the machine and validate the current rig profile before a session:

```bash
rpi-vstim doctor --config config/rigs/pi5_default.toml
rpi-vstim config validate config/rigs/pi5_natural_image_demo.example.toml
```

### Natural-image run

This example uses the current Pi 5 profile, which enables the validated
stimulus display, left/right lick inputs, two cameras, preview, and fail-closed
NVMe storage. Replace the example mouse identifier and review the profile
before starting hardware:

```bash
rpi-vstim natural-images run \
  --mouse-id V1_2 \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --licks --cameras --camera-preview
```

### Audio-only pilot

Run the safe fake six-trial plan first:

```bash
rpi-vstim audio-pilot --simulate --smoke \
  --config config/rigs/pi5_audio_pilot.example.toml \
  --output-root /tmp/rpi-vstim-audio-sessions
```

The optional physical smoke plays beep, buzz, and white noise twice each. Each
preloaded WAV is 3 seconds and playback uses one persistent stream:

```bash
rpi-vstim audio-pilot \
  --smoke \
  --config config/rigs/pi5_audio_pilot.example.toml \
  --output-root /mnt/behavbox_ssd/sessions
```

The current adapter is the C-Media / Unitek Y-247A USB Audio Device feeding a
3.5 mm analog speaker. This standalone test does not validate audio alongside
the visual/camera stack. Callback timestamps are software timing, not
measured acoustic onset.
The digital WAVs have matched RMS, not matched perceived loudness or SPL;
animal-facing gains require SPL measurement at the mouse position. Details:
[audio pilot](docs/audio_pilot.md) and
[pilot WAVs](assets/audio/pilot/README.md).

### Visual + audio coexistence run

The opt-in integration mode runs the natural-image KMS sequence, both cameras,
session logging, and scheduled USB audio together. This exact two-minute
configuration was validated on the Pi 5; it plans eight sounds beginning at
10 seconds. It is a short coexistence check, not audio endurance validation or
an animal-calibrated task:

```bash
rpi-vstim natural-images run \
  --mouse-id <identifier> \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --image-count 84 --seed 0 --cameras --audio-coexistence \
  --audio-config config/rigs/pi5_audio_pilot.example.toml \
  --output-root /mnt/behavbox_ssd/sessions
```

See the [coexistence validation record](docs/hardware/pi5_av_coexistence_2026-10-16.md)
for the actual session results and limits.

### Simulation

This creates a simulated session without Pi display, camera, GPIO, audio, or
production storage:

```bash
rpi-vstim run drifting-gratings --simulate \
  --output-root /tmp/rpi-vstim-sim
```

The drifting-grating plan is software groundwork only; simulation success is
not hardware validation.

## Configuration and data

Use TOML profiles. `pi5_default.toml` is a hardware-neutral Pi 5 starting
profile; `simulation.toml` uses fake services; the `pi5_*` example profiles
contain deployment-specific display, camera, GPIO, and storage settings. The
natural-image profile writes directly to
`/mnt/behavbox_ssd/sessions/<session-id>` and fails closed if the expected NVMe
mount is absent. Generic profiles do not require that SSD. See
[configuration](docs/configuration.md) and [storage](docs/storage.md).

Sessions are self-contained directories. Depending on enabled services they
can include `events.jsonl`, final status, resolved config and provenance,
stimulus plan and image manifest, camera manifests and MP4s, and the retained
display/KMS trace. Audio sessions also include copied pilot WAVs,
`audio_manifest.json`, and `audio_summary.json`. Optional artifacts are absent
when their service is not used. Fast camera QC checks bounded container
metadata; it does not decode every frame. `rpi-vstim inspect-session PATH
--deep-camera-qc` requests the slower frame-count/decode checks.

The canonical natural-image corpus path is
`assets/natural_images/stringer_natimg2800_center_crop/`. It is present in this
checkout. The repository does not establish dataset licensing terms; verify
those terms before any redistribution outside the lab. User-supplied corpora
can be selected through configuration.

## Timing, cameras, and GPIO

`CLOCK_MONOTONIC` is authoritative for within-session ordering; `CLOCK_SYNC`
maps it to UTC. KMS/kernel vblank or page-flip timestamps record actual display
presentation where available. Occasional extended refresh intervals can
occur, so analyze recorded timestamps rather than assuming every refresh met
the nominal period. Camera MP4 PTS is retained; per-frame hardware camera
timestamps are not claimed. See [timing](docs/timing.md).

Two local CSI cameras can record MP4 directly to the session, with operator
preview and coordinated shutdown. GPIO is profile-configured. Read-only
diagnostics do not claim pins; the GPIO input example requires an explicit pin.
GPIO9 is reserved for NeuroKairos IRIG. GPIO23/24 are unassigned on the current
rig. No reward, vacuum, or airpuff output is activated by the examples. See
[camera workflow](docs/cameras.md) and [GPIO policy](docs/gpio.md).

## Protocols

| Protocol | Current state |
|---|---|
| Natural images | Real Pi 5 demo runner and integrated validation are available |
| Audio pilot | Persistent USB playback, audio-only pilot, and opt-in same-session natural-image/audio coexistence are implemented; the coexistence path passed a ~2-minute Pi 5 run |
| Drifting gratings | Seeded planner and root-level compatibility wrapper exist; not validated through the current Pi KMS runner |
| Retinotopy | Seeded sweep planner and root-level compatibility wrapper exist; geometry/rendering and current Pi KMS validation remain pending |

Start with [writing a protocol](docs/writing_protocols.md). The intended split
is reusable session/hardware services beneath protocol-specific planning and
trial logic. NeuroKairos is external: VStim does not start or stop its sender,
and never acquires GPIO9. IRIG can support offline timing alignment when it is
physically recorded by the relevant camera or acquisition system.

## Internal lab setup

Use Python `>=3.13,<3.14`, install system-level Pi dependencies for the
services you use, select a reviewed rig profile, and run `doctor` before a
hardware session. Historical validation records remain in
[docs/hardware](docs/hardware/); current rig wiring and unresolved apparatus
tasks are summarized in [docs/pi5_rig.md](docs/pi5_rig.md).
