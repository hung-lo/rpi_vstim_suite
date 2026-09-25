# rpi_vstim_suite

Phase 00 bootstrap for a Raspberry Pi 5 visual-stimulus suite.

The package is a hardware-safe Phase 00 and overnight software-groundwork
implementation. It provides deterministic natural-image and reward-planning
logic, a fake display, simulated hardware, bounded telemetry, session
manifests, and metadata-only dual-local-camera supervision. Real display,
camera capture, GPIO, network telemetry, and reward actuation remain deferred.

The production architecture is one Raspberry Pi 5 for stimulus presentation,
GPIO/lick/reward control, logging, telemetry, and two independently configured
local cameras. `rpi_rig_monitor` remains a separate monitor Pi and repository.

```bash
python -m pip install -e '.[dev]'
rpi-vstim --help
rpi-vstim list-protocols
rpi-vstim config validate config/system.example.toml
rpi-vstim run natural-images --simulate --output-root /tmp/rpi-vstim-sim
rpi-vstim run reward-conditioning --simulate --output-root /tmp/rpi-vstim-sim
```

The old repositories and `rpi_rig_monitor` remain separate reference
repositories. No old Git history is merged here.
