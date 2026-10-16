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

The optional `UdpTelemetryPublisher` uses a nonblocking local AF_UNIX datagram
handoff and a daemon worker that owns UDP transmission. The parent converts
one small payload to compact JSON and performs one nonblocking local datagram
send; it never opens a network socket or waits for the monitor. Handoff
overflow, serialization errors, and worker send errors are counted and are
non-fatal unless the caller marks telemetry as required. `rpi-vstim telemetry
demo` and `rpi-vstim telemetry benchmark` exercise only a loopback receiver.

The current simulated and virtual runtimes still inject null/in-memory
publishers. Wiring the UDP publisher into the future real unified session
runner, and validating it against the separate monitor, remain separate gates.
