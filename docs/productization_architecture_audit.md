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
a separate fail-closed Box151 NVMe check. Public package entry points are
currently sparse; useful classes live in submodules. Dependency direction is
mostly protocol/CLI to core and backends; config imports the GPIO pin policy.
Simulation uses fake display, simulated hardware/cameras, and in-memory
telemetry. Tests are grouped into unit, contract, integration, stress, and
hardware directories.

Box151 assumptions are concentrated in the real natural-image demo, its rig
TOML, the production storage guard, the GPIO policy, and old default paths.
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
`core.natural_image_demo` and its CLI text are Box151-specific integration
code. `core.storage` contains the intentional fail-closed Box151 NVMe guard.
`hardware.policy` contains the intentional GPIO9 safety guard. The rig TOML
files with fixed connectors/topology are deployment profiles. `docs/hardware`,
the older phase pages, and archived plans are historical evidence; the new
guides separate the generic API from that deployment. The accidental generic
`/mnt/hd` and `/home/pi` path defaults were removed. Generic/simulation
profiles explicitly leave GPIO roles unassigned; the inherited dataclass map
remains for legacy config compatibility and is never acquired implicitly.
