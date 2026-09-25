# Telemetry protocol

The experiment-side boundary reserves outer schema version 1 and telemetry
payload schema version 3 for the separate `rpi_rig_monitor` consumer. The
software-groundwork message includes message type, session/protocol identity,
lifecycle/phase, UTC timestamp, sequence number, optional trial/stimulus fields,
counters, camera status, and degraded/error state. The outer packet is flat and
uses `type = state` for lifecycle packets and `type = trial_complete` for
trial packets; the payload also retains compatibility aliases such as `image`,
`trial`, and `camera_states`.

`camera_states` and the full `cameras` list are authoritative. The legacy
singular `camera_state` is an aggregate: any required `FAILED` camera yields
`FAILED`; optional `FAILED` or any `DEGRADED` camera yields `DEGRADED`; two
healthy `RECORDING` cameras yield `RECORDING`. It is never selected from a
fixed camera index.

Phase 00 and overnight simulation use null or bounded in-memory publishers:
they open no socket and send no packets. Monitor loss remains non-fatal unless
configuration explicitly marks telemetry as required.
