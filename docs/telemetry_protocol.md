# Telemetry protocol

The experiment-side boundary reserves outer schema version 1 and telemetry
payload schema version 3 for the separate `rpi_rig_monitor` consumer. Phase 00
uses a null publisher: it opens no socket and sends no packets.

