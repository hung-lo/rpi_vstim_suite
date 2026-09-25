# Architecture

The package is split into core session services, protocol placeholders,
display, hardware, local camera, and telemetry boundaries. The production
experiment runtime is one Raspberry Pi 5 owning stimulus presentation,
GPIO/lick/reward control, session logging, telemetry, and two local cameras.
`rpi_rig_monitor` remains a separate monitor Pi and repository.

Phase 00 uses only the fake display, simulated hardware, and null telemetry
publisher on a desktop. Its schema represents cameras as independent local
devices with stable identities; it does not capture frames or open devices.

Future timing-sensitive work must keep display and GPIO workers separate from
disk, terminal, camera, and network operations. Each camera will eventually
have its own supervised worker with bounded buffering and direct-to-disk
recording; no camera work belongs in the timing-critical process. The audited
experiment Pi has 2 GB RAM, so buffering and stimulus caching must remain
bounded and be measured under simultaneous load.
