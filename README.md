# rpi_vstim_suite

Phase 00 bootstrap for a Raspberry Pi 5 visual-stimulus suite.

The package is a hardware-safe Phase 00 skeleton: configuration, CLI wiring,
fake display, simulated GPIO, session metadata, and protocol placeholders are
present, while display, camera capture, GPIO, telemetry, and experiment
execution remain deferred.

The production architecture is one Raspberry Pi 5 for stimulus presentation,
GPIO/lick/reward control, logging, telemetry, and two independently configured
local cameras. `rpi_rig_monitor` remains a separate monitor Pi and repository.

```bash
python -m pip install -e '.[dev]'
rpi-vstim --help
rpi-vstim list-protocols
rpi-vstim config validate config/system.example.toml
```

The old repositories and `rpi_rig_monitor` remain separate reference
repositories. No old Git history is merged here.
