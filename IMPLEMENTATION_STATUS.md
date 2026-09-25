# Implementation status

This status uses the phase numbering from
`RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md` (V2).

## Phase 0 — source freeze and migration inventory

- [x] Read the canonical implementation plan.
- [x] Record the four source repositories, commits, and migration ownership.
- [x] Record the legacy Box151 calibration as a reference-only profile.
- [x] Preserve assignment/state handling as reference-only; no target state
  files were copied, reformatted, or modified.
- [x] Complete the source behavior ownership/migration inventory.

**Gate 0: satisfied for the current source inventory.**

## Phase 1 — repository skeleton and fake runtime

- [x] Add Python 3.13 package metadata and CLI skeleton.
- [x] Add TOML configuration dataclasses and validation.
- [x] Add fake display and simulated hardware boundaries.
- [x] Add session, lifecycle, provenance, event logging, and output skeletons.
- [x] Add protocol placeholders and compatibility wrappers.
- [x] Add deterministic protocol planning and golden/contract coverage.
- [x] Add metadata-only fake supervision for two local cameras.
- [x] Add simulated failure handling, cleanup, and bounded telemetry contracts.
- [x] Add end-to-end simulated acceptance tests.

**Gate 1: satisfied by the simulated session path and test suite.**

The completed Phase 0/1 work is software groundwork only. It does not claim
that any Pi 5 hardware backend or physical acceptance test has passed.

## Phase 2 — Pi 5 audit and bootstrap

Phase 2 is the current hardware-gated stage.

- [x] Run the current read-only SSH audit at `pi@10.42.84.10`; the complete
  report is `docs/hardware/pi5_phase2_audit_2026-09-25.md`.
- [x] Identify both physical local cameras, stable identities, supported
  modes, and USB/CSI/media topology.
- [x] Install the minimal Phase 2 DRM/EDID diagnostic packages from verified
  Debian Trixie package metadata.
- [x] Characterize both DRM HDMI connectors, EDIDs, preferred modes, active
  modes, and available refresh rates without setting a mode.
- [x] Individually open both CSI cameras with the installed `rpicam-*` stack
  using one-second no-preview smoke tests.
- [ ] Measure writable target storage and concurrent dual-camera write
  throughput.
- [ ] Create and review the actual Pi 5 rig profile.
- [ ] Resolve any OS, Python, mount, permission, or time-sync issues.
- [ ] Bootstrap only after the audit is reviewed; confirm runtime needs no
  root privileges.

**Gate 2 overall: incomplete; storage sub-gate deferred.** Pi platform
readiness, camera enumeration readiness, and display discovery readiness are
verified enough for the scoped display-only work authorized by the addendum.
Production storage readiness remains deferred until the experiment SSD is
attached. The fstab-referenced storage UUID is absent and `/mnt/hd` has no
mapping. The provisional display-role mapping is user-authorized, not a new
physical verification.

### Phase 2 follow-up — 2026-09-25

- [x] Confirm the fstab storage entry and verify that its UUID-backed device is
  absent; no speculative mount or `/etc/fstab` change was made.
- [x] Install `libdrm-tests`, `drm-info`, and `edid-decode`, plus required
  libdrm dependencies, with no desktop environment or unrelated graphics
  stack.
- [x] Confirm the active mode is `1024x600@59.82` on both connected HDMI
  connectors; HDMI-A-1 prefers `1024x600@59.821` and advertises `1280x720`
  modes, while HDMI-A-2 advertises only `1024x600`.
- [x] Confirm `rpicam-apps` 1.11.1/libcamera 0.7.0 and pass individual
  no-preview open smoke tests for both cameras.
- [ ] Resolve the absent experiment storage and select the intended physical
  display before claiming the full Gate 2.

The package installation is a Phase 2 bootstrap change. No mount, boot,
persistent configuration, mode-setting, full-screen stimulus, or production
camera supervisor was started. Concurrent dual-camera load and production
storage remain later acceptance work.

### Scoped Phase 3 display-only work — SSD-independent

- [x] Add configurable `stimulus_connector` and `preview_connector` roles.
- [x] Add strict connector/mode/refresh selection with no silent fallback.
- [x] Add hardware-independent DRM parser/selection fixtures and tests.
- [x] Add read-only `rpi-vstim hardware display-probe` plumbing.
- [x] Add a fail-closed KMS open/validation boundary; frame presentation still
  requires the native page-flip layer.
- [ ] Implement and hardware-test native page-flip/vblank presentation,
  photodiode timing, and safe CRTC restoration.

Provisional user-authorized mapping: `HDMI-A-1` is the stimulus display and
`HDMI-A-2` is the camera-preview display. This remains configurable and is not
presented as physically re-verified.

## Historical hardware evidence

The earlier audit is retained as historical inventory evidence. The complete
V2 Phase 2 report is
`docs/hardware/pi5_phase2_audit_2026-09-25.md`. No target files, services,
boot settings, groups, permissions, or camera controls were changed by this
audit.

## Deferred until the relevant hardware gate

Real display/KMS, GPIO, camera acquisition, UDP send, asset conversion,
reward actuation, and production experiment execution remain deferred. The
separate `rpi_rig_monitor` Pi remains outside this phase and is unchanged.
