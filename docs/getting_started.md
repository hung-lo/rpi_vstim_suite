# Getting started

The validated target is Raspberry Pi 5, Debian 13/Trixie, Python 3.13. Install
system tools separately: `rpicam-*` for CSI cameras, `ffprobe` for MP4 QC,
`lgpio` Python bindings for GPIO, and `libdrm` development files plus a C
compiler for native KMS. These are system dependencies, not pip requirements.
Build `native/kms_display` with `make` on the Pi when using KMS; see its
[README](../native/kms_display/README.md).

```bash
git clone https://github.com/hung-lo/rpi_vstim_suite.git
cd rpi_vstim_suite
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-build-isolation -e .
rpi-vstim --version
```

The venv needs `setuptools`. For development, install `.[dev]` and run
`python -m pytest`; non-Pi machines need Python 3.13 but no Pi devices.

1. `rpi-vstim doctor --config config/rigs/pi5_default.toml` inspects only.
2. `rpi-vstim hardware display-probe --config <rig.toml>` reads connector modes.
3. `rpi-vstim hardware kms-render-smoke --config <rig.toml> --frames 60`
   explicitly presents a short pattern and restores the display.
4. `python examples/dual_camera_recording.py --config <rig.toml> --seconds 10`
   records configured cameras. Use a non-production output root while learning.
5. `python examples/gpio_input.py --pin <input BCM pin> --output edges.jsonl`
   explicitly claims one input; it never drives an output.
6. `python examples/minimal_session.py --output-root /tmp/vstim-demo --display`
   demonstrates session output. Then inspect protocols with
   `rpi-vstim list-protocols` and `rpi-vstim preflight`.

The fake `minimal_display.py` and `image_sequence.py` run without hardware.
The real natural-image command is documented under [current Pi 5 deployment](pi5_rig.md).
