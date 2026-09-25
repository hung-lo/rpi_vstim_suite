# Telemetry protocol

The experiment-side boundary reserves outer schema version 1 and telemetry
payload schema version 3 for the separate `rpi_rig_monitor` consumer. The
software-groundwork message includes message type, session/protocol identity,
lifecycle, sequence number, optional trial/stimulus fields, counters, camera
status, and degraded/error state.

Phase 00 and overnight simulation use null or bounded in-memory publishers:
they open no socket and send no packets. Monitor loss remains non-fatal unless
configuration explicitly marks telemetry as required.
