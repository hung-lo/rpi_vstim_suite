# rpi_vstim_suite

Phase 00 bootstrap for a Raspberry Pi 5 visual-stimulus suite.

The package is intentionally non-hardware-safe at this stage: configuration,
CLI wiring, fake display, simulated GPIO, session metadata, and protocol
placeholders are present, while display, camera, GPIO, telemetry, and
experiment execution remain deferred.

```bash
python -m pip install -e '.[dev]'
rpi-vstim --help
rpi-vstim list-protocols
rpi-vstim config validate config/system.example.toml
```

The old repositories and `rpi_rig_monitor` remain separate reference
repositories. No old Git history is merged here.

