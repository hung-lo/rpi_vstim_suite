# Architecture

The package is split into core session services, protocol placeholders,
display, hardware, camera, and telemetry boundaries. Phase 00 uses only the
fake display, simulated hardware, and null telemetry publisher on a desktop.

Future timing-sensitive work must keep display and GPIO workers separate from
disk, terminal, camera, and network operations.

