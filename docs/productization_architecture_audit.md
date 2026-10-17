# v0.1 architecture audit

Audited at `00baaa2` before the productization changes.

The package tree has `core` (config, lifecycle, session, events, storage,
timestamps, provenance), `display` (fake and KMS backends), `camera` (identity
and supervisor), `hardware` (simulated and lgpio services), `protocols`
(natural images, drifting gratings, retinotopy, reward conditioning, spout
training), `telemetry`, `validation`, and `tools`. The top-level CLI is
`rpi_vstim.cli`; `rpi-vstim` is its installed entry point. Existing commands
include protocol listing, preflight, simulation, virtual run, the real
natural-image demo, session inspection, read-only display probes, explicit
KMS smoke, operator/water controls, and config validation. `doctor` was a
placeholder.

TOML is mapped to frozen dataclasses in `core.config`. Validation already
catches duplicate pins, reserved GPIO9, required camera identities, and
unsafe experimental combinations. `core.storage` has generic preflight and
a separate fail-closed current Pi 5 NVMe check. Public package entry points are
currently sparse; useful classes live in submodules. Dependency direction is
mostly protocol/CLI to core and backends; config imports the GPIO pin policy.
Simulation uses fake display, simulated hardware/cameras, and in-memory
telemetry. Tests are grouped into unit, contract, integration, stress, and
hardware directories.

Current Pi 5 assumptions are concentrated in the real natural-image demo, its
rig TOML, the production storage guard, the GPIO policy, and old default paths.
Pi-specific backends are imported without acquiring devices; actual access
occurs only on explicit run/probe. The generic default paths and stale docs
need cleanup. The validated KMS, camera, event, and storage internals already
have useful boundaries and need no restructuring. Existing docs mix current
reference pages with historical hardware reports; the entry path needs a
new-user guide. This pass changes callers/config profiles, CLI diagnostics,
exports, examples, and docs while keeping validated run paths stable.

## Assumption search

Search terms: `Box151`, `behavbox`, `/mnt/behavbox_ssd`, `V1_2`, `GPIO9`,
`connector42`, `connector33`, `HDMI-A-1`, `HDMI-A-2`, `/home/pi`.
Box151 is the older 2-photon rig and appears legitimately in the legacy Pi 4
profile, reference calibration, and archived planning documents. The first
productization draft incorrectly applied that name to the current Pi 5 rig;
the correction pass removed those uses. `core.natural_image_demo` and its CLI
text are current Pi 5 integration code. `core.storage` contains the
intentional fail-closed current-rig NVMe guard.
`hardware.policy` contains the intentional GPIO9 safety guard. The rig TOML
files with fixed connectors/topology are deployment profiles. `docs/hardware`,
the older phase pages, and archived plans are historical evidence; the new
guides separate the generic API from that deployment. The accidental generic
`/mnt/hd` and `/home/pi` path defaults were removed. Generic/simulation
profiles explicitly leave GPIO roles unassigned; the inherited dataclass map
remains for legacy config compatibility and is never acquired implicitly.
Current-rig profiles leave GPIO23/24 and the legacy GPIO23 operator button
unassigned. The current audio path uses a USB adapter; no audio backend is
part of the original productization audit.

## Audio and AV follow-up — 2026-10-16

Later commits added a small `rpi_vstim.audio` interface backed optionally by
`sounddevice`/PortAudio and an audio-only pilot protocol. It preloads the
three committed WAVs into memory and keeps one output stream open. The current
Pi 5 rig uses a USB audio adapter; GPIO23 and GPIO24 remain unassigned and
have no audio role. Standalone USB playback has been characterized. Commit
`dc3cdd2855cdde8574f23bdcd73d9df522fd513e` adds the opt-in
`natural-images run --audio-coexistence` integration path using the existing
KMS/session/camera runtime and audio backend. That exact source was used for
the approximately two-minute Pi coexistence run; its session and measurements
are recorded in [the AV validation report](hardware/pi5_av_coexistence_2026-10-16.md).
The integration result does not imply audio endurance, acoustic calibration,
or a general behavioral audiovisual protocol.
