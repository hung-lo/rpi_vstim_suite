# Architecture

The package is split into core session services, software-groundwork protocol
planners,
display, hardware, local camera, and telemetry boundaries. The production
experiment runtime is one Raspberry Pi 5 owning stimulus presentation,
GPIO/lick/reward control, session logging, telemetry, and two local cameras.
`rpi_rig_monitor` remains a separate monitor Pi and repository.

Phase 00 and overnight simulation use only the fake display, simulated
hardware, and null or bounded in-memory telemetry publisher on a desktop. The
schema represents cameras as independent local devices with stable identities;
the fake service records start/stop intent and state but never captures frames
or opens devices.

Future timing-sensitive work must keep display and GPIO workers separate from
disk, terminal, camera, and network operations. Each camera will eventually
have its own supervised worker with bounded buffering and direct-to-disk
recording; no camera work belongs in the timing-critical process. The audited
experiment Pi has 2 GB RAM, so buffering and stimulus caching must remain
bounded and be measured under simultaneous load.
