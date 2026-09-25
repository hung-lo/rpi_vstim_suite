# rpi_vstim_suite

V2 software groundwork and SSD-independent display bring-up for a Raspberry
Pi 5 visual-stimulus suite.

The package provides deterministic protocol planning, a fake display, simulated
hardware, bounded telemetry, session manifests, metadata-only dual-local-camera
supervision, configurable display roles, and read-only DRM mode discovery.
Native page-flip presentation, production camera capture, GPIO, network
telemetry, reward actuation, and production storage remain hardware-gated.

The production architecture is one Raspberry Pi 5 for stimulus presentation,
GPIO/lick/reward control, logging, telemetry, and two independently configured
local cameras. `rpi_rig_monitor` remains a separate monitor Pi and repository.

```bash
python -m pip install -e '.[dev]'
rpi-vstim --help
rpi-vstim list-protocols
rpi-vstim config validate config/system.example.toml
rpi-vstim hardware display-probe --config config/rigs/pi5_dual_display_provisional.example.toml
rpi-vstim run natural-images --simulate --output-root /tmp/rpi-vstim-sim
rpi-vstim run reward-conditioning --simulate --output-root /tmp/rpi-vstim-sim
rpi-vstim run spout-training --simulate --output-root /tmp/rpi-vstim-sim
rpi-vstim run drifting-gratings --simulate --output-root /tmp/rpi-vstim-sim
rpi-vstim run retinotopy --simulate --output-root /tmp/rpi-vstim-sim
```

For an explicit protocol TOML, pass `--config`; the configured protocol name
must match the command. With no config, the CLI selects the named software
groundwork protocol and uses the fake display, simulated hardware, and bounded
telemetry sink. Run `python -m pytest -q`, `python -m compileall -q src tests`,
and `bash -n scripts/*.sh` before review. The target is Python 3.13; if local
Python 3.13 is unavailable, use a repo-local validation environment and record
the interpreter version rather than changing the system Python.

The old repositories and `rpi_rig_monitor` remain separate reference
repositories. No old Git history is merged here.
