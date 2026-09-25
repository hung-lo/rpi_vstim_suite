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
- [x] Implement the standalone direct-libdrm probe and bounded native
  alternating-pattern/page-flip path.
- [x] Add Python KMS wrapper/result conversion and timing-statistics helpers.
- [x] Add configurable photodiode patch geometry/value plumbing and tests.
- [x] Validate native read-only connector/CRTC/primary-plane discovery on both
  real Pi HDMI outputs.
- [x] Characterize the live LightDM/labwc DRM-master topology and verify the
  Wayland DRM-lease global plus both HDMI connector offers without requesting a
  lease.
- [x] Separate native access/resource compatibility diagnostics from
  modesetting ownership and page-flip status; add compositor-ownership error
  classification and synthetic dropped-frame statistics.
- [x] Add an isolated Wayland DRM-lease client boundary, lease-fd handoff to
  the existing native KMS path, and hardware-independent lease lifecycle tests.
- [x] Diagnose and fix the first DRM-lease client SIGSEGV: the hand-written
  v1 binding omitted the connector/lease destructor request metadata. Add
  explicit release acknowledgment handling, sanitizer/self-test coverage, and
  a Pi enumeration-only preflight without submitting a lease.
- [x] Complete the first post-fix supervised HDMI-A-1-only lease probe:
  `drmModeGetLease()` returned connector 33, primary plane 81, CRTC 92, and
  cursor plane 655; HDMI-A-2 remained compositor-managed and release restored
  labwc. No modeset or page flip was performed.
- [x] Validate the first leased HDMI-A-1 modeset and 300 native page flips at
  1024x600 RGB565; collect software vblank timing with zero missed/dropped
  intervals and verify CRTC/lease/compositor recovery.
- [ ] Validate physical timing, long-duration acceptance, and final CRTC
  restoration criteria; the active `labwc` DRM owner still requires the lease
  path for future runs.
- [ ] Test an HDMI-A-1-only DRM lease, including leased object IDs, page flips,
  HDMI-A-2 preview continuity, revocation, and recovery; the first supervised
  probe-only request terminated with a native client segmentation fault before
  reporting a lease object set. The post-fix acquisition/object/recovery probe
  and 300-frame native page-flip run passed; revocation, long-duration, and
  integrated testing remain pending. See
  `docs/hardware/pi5_phase3_drm_lease_2026-09-25.md`.
- [ ] Integrate production frame-cache loading and protocol rendering.

Provisional user-authorized mapping: `HDMI-A-1` is the stimulus display and
`HDMI-A-2` is the camera-preview display. This remains configurable and is not
presented as physically re-verified.

The native probe compiled on the Pi with Debian Trixie `libdrm-dev`. Its
read-only mode returned HDMI-A-1/CRTC 92/primary plane 81 and
HDMI-A-2/CRTC 104/primary plane 93; both primary planes advertise `RG16`
(DRM RGB565). A one-frame HDMI-A-1 modeset attempt failed before modesetting
with an explicit DRM-master ownership diagnostic because `labwc` owns
`/dev/dri/card1`. The active Wayland registry exposes `wp_drm_lease_device_v1`
and offers both HDMI connectors. After the binding fix, the Pi sanitizer
preflight enumerated HDMI-A-1/connector 33 and HDMI-A-2/connector 42 and
cleanly released the device without submitting a lease. No compositor or
session configuration was changed. See
`docs/hardware/pi5_phase3_display_ownership_2026-09-25.md`.

**Canonical Gate 3: not satisfied.** The software implementation, native
read-only resource proof, live lease capability discovery, offline binding
preflight, the first supervised lease/object/recovery probe, and the first
300-frame leased modeset/page-flip run are complete. Physical photodiode
validation, long-duration acceptance, production frame-cache rendering, and
integrated hardware acceptance remain unverified or deferred.

## Historical hardware evidence

The earlier audit is retained as historical inventory evidence. The complete
V2 Phase 2 report is
`docs/hardware/pi5_phase2_audit_2026-09-25.md`. No target files, services,
boot settings, groups, permissions, or camera controls were changed by this
audit.

## Deferred until the relevant hardware gate

Real display timing acceptance, production frame rendering, GPIO, camera
acquisition, UDP send, asset conversion, reward actuation, and production
experiment execution remain deferred. The separate `rpi_rig_monitor` Pi
remains outside this phase and is unchanged.
