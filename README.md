# rpi_vstim_suite

Reusable Raspberry Pi visual stimulus and behavioral session building blocks:
Pi 5 KMS presentation, local cameras, GPIO services, event and timing logs,
session storage, and protocol planning.

## Supported platform

Raspberry Pi 5 on Debian 13/Trixie with Python `>=3.13,<3.14` is the validated
hardware target. Fake display, camera, and GPIO services support development
on other machines with a compatible Python. Other hardware is not claimed.

## Quick start

Install system tools for your chosen hardware services separately, then:

```bash
git clone https://github.com/hung-lo/rpi_vstim_suite.git
cd rpi_vstim_suite
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-build-isolation -e .
rpi-vstim doctor --config config/rigs/pi5_default.toml
```

The venv needs `setuptools`. The `dev` extra adds pytest/Ruff; `images` adds
Pillow. See [getting started](docs/getting_started.md) for system tools and
native KMS build steps.

## Safe demo

```bash
python examples/minimal_display.py
python examples/minimal_session.py --output-root /tmp/rpi-vstim-examples --display
rpi-vstim run drifting-gratings --simulate --output-root /tmp/rpi-vstim-sim
```

These use fake services. `doctor --json` inspects a Pi without acquiring
devices. The [getting started guide](docs/getting_started.md) gives the
progression from environment check to display, camera, GPIO, and protocol.

## Configuration and session output

TOML profiles select display, camera identities, GPIO wiring, and output root.
`pi5_default.toml` and `simulation.toml` are neutral starting points;
`pi5_natural_image_demo.example.toml` is the current Pi 5 deployment
profile. See [configuration](docs/configuration.md).

Each session has a unique directory under its configured output root with
resolved config, provenance, status, and event/display results. Camera files,
KMS trace, stimulus plan, and image provenance are conditional. See
[storage](docs/storage.md) for artifacts and the current rig's NVMe guard.

## Timing, cameras, and GPIO

`CLOCK_MONOTONIC` orders within-session events; `CLOCK_SYNC` maps it to UTC.
Kernel/KMS timestamps describe actual presentation. Rare extended refreshes
can occur, so analyze recorded timing rather than nominal refresh. Camera MP4
PTS is available; per-frame camera hardware timestamps are not claimed. See
[timing](docs/timing.md).

Two local CSI cameras can record with preview, coordinated shutdown, and
bounded fast MP4 QC. `rpi-vstim inspect-session PATH --deep-camera-qc` performs
slower offline counting. See [cameras](docs/cameras.md).

GPIO is configured per rig. Doctor never claims pins; input examples require
an explicit pin. The current rig reserves BCM GPIO9 for external NeuroKairos
IRIG and assigns GPIO23/24 to WAV Trigger inputs. See
[GPIO](docs/gpio.md).

## Protocols and validation

[Writing protocols](docs/writing_protocols.md) starts with a minimal session
and explains planning, services, events, Ctrl-C, and finalization. The
natural-image runner is an integrated protocol; users supply their own corpus
as described in [natural-image assets](docs/natural_image_assets.md).

[current Pi 5 deployment](docs/pi5_rig.md) and [hardware records](docs/hardware/)
describe validation. Fluidics, final spout construction, and animal reward
calibration remain rig-specific. NeuroKairos is an optional external service;
VStim never starts it or acquires GPIO9.

Version `0.1.0` denotes the Pi 5 core framework, not validation of every
apparatus. No natural-image dataset license is asserted here.
