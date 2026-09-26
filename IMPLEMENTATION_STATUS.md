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
physically attached. The SSD is now reportedly available but its device,
UUID, mount point, and `/mnt/hd` mapping remain unverified; the fstab intent
must be checked when it is connected. The current HDMI role mapping was later
physically corroborated during Phase 3 and remains configurable.

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
- [ ] Connect and resolve the experiment SSD, then verify the intended mount
  and storage path before claiming the full Gate 2.

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
- [x] Complete the corrected HDMI-A-2-only 10,000-frame leased RGB565 run at
  1024x600; the lease contained connector 42/CRTC 104/primary plane 93 and
  cursor plane 666, excluded HDMI-A-1/connector 33, and restored labwc.
- [x] Validate HDMI-A-2 XRGB8888 compatibility with a clean 300-frame leased
  run; RGB565 remains the default because it uses half the scanout memory with
  no measured timing disadvantage.
- [x] Integrate a bounded production frame renderer with reusable scanout
  buffers, RGB565/XRGB8888 conversion, deterministic frame indexing, and
  photodiode patch application through the existing leased KMS backend.
- [x] Run the production-renderer smoke path on real HDMI-A-2 hardware for
  300 leased page flips with an external prepared frame pair.
- [x] Run a short real simultaneous dual-camera smoke using stable IMX708
  sensor/topology identities and the installed `rpicam-*` stack; both workers
  captured concurrently for 15 seconds and exited successfully.
- [x] Run one short combined HDMI-A-2 leased production-renderer plus
  two-camera test; 3,600/3,600 page flips completed, HDMI-A-1 remained
  compositor-managed, and compositor/display recovery succeeded. The full
  trace and resource samples are in
  `docs/hardware/pi5_phase3_combined_display_camera_2026-09-25.json` and
  `docs/hardware/pi5_phase3_combined_resources_2026-09-25.log`.
- [x] Analyze the historical combined callback trace without changing the
  authoritative hardware result: all 105 long intervals are immediately
  compensated by a following below-nominal interval, all 105 short intervals
  have a preceding above-nominal interval, and frame/kernel sequences remain
  contiguous. These are callback-dispatch intervals, not kernel-vblank or
  optical measurements. See
  `docs/hardware/pi5_phase3_timing_analysis_2026-09-25.md`.
- [x] Exercise one controlled combined interruption/recovery path; no orphan
  camera/KMS processes remained and both stable cameras re-enumerated.
- [ ] Validate physical photodiode timing and long-term optical behavior; the
  required acquisition hardware is unavailable and final-screen wiring is not
  yet relevant. This is deferred, not a near-term blocker.

- [x] Verify the physical display roles with a controlled leased pattern:
  `HDMI-A-2` is the visual-stimulus display and `HDMI-A-1` is the
  camera-monitor display. A photo/manual cable trace additionally confirms
  physical HDMI0 (nearest the USB-C power input) maps to DRM HDMI-A-1 and
  physical HDMI1 maps to DRM HDMI-A-2. The mapping remains configurable in
  the Pi 5 rig profile.

The earlier HDMI-A-1 10,000-frame RGB565 attempt was intentionally interrupted
at 9,972 completed frames after the physical-role mismatch was observed. It is
recorded as general lease/KMS endurance and mapping-discovery evidence, not as
stimulus-display acceptance. The corrected HDMI-A-2 run is the authoritative
stimulus-display endurance result.

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

**Canonical Gate 3: not satisfied.** DRM leasing, corrected HDMI-A-2
long-duration software timing, XRGB8888 compatibility, bounded production
frame preparation, real-Pi production-renderer timing, compositor recovery,
HDMI-A-1 continuity, and physical connector-role discovery are complete.
Physical photodiode timing, asset-level natural-image acceptance, storage
validation, production camera-supervisor stop semantics, timing acceptance
under the eventual camera and storage workload, and integrated
camera/GPIO/reward acceptance remain unverified or deferred. The current
display work validates the Pi 5 DRM lease/KMS architecture and the present
display; it is not final optical timing certification of the eventual rig.
The eventual stimulus display may change, including to the OL7 used on the 2P
setup. If it changes, re-audit EDID/mode/refresh, rerun leased page-flip and
production-renderer timing, and perform photodiode validation only when the
final screen and acquisition hardware are available. The combined smoke is
readiness evidence only. Its 105 long and 105 short intervals form adjacent
compensating callback-dispatch excursions in the historical schema; they do not
establish kernel-vblank or optical timing. The possible brief flashes still
require physical photodiode validation. User observation reported generally
normal stimulus output with a few possible brief flashes, stable camera-monitor
output, and normal recovery; this is not visual acceptance.

## Historical hardware evidence

The earlier audit is retained as historical inventory evidence. The complete
V2 Phase 2 report is
`docs/hardware/pi5_phase2_audit_2026-09-25.md`. No target files, services,
boot settings, groups, permissions, or camera controls were changed by this
audit.

## Deferred until the relevant hardware gate

Physical display/optical timing acceptance, production camera
acquisition/supervision, GPIO, UDP send, asset conversion, reward actuation,
and production experiment execution remain deferred. The short `rpicam-*`
smoke is hardware evidence, not a production camera backend. The separate
`rpi_rig_monitor` Pi remains outside this phase and is unchanged.

When the SSD is physically connected, storage work takes priority: identify
the device/UUID/mount point, verify existing `/etc/fstab` intent, verify
mount/read/write/free space, run conservative throughput testing, run
sustained two-camera recording to the SSD, and run combined leased display +
two-camera + SSD-write load while collecting RAM, CPU, temperature, throttling,
and display timing. The Pi SD card must not be used as a substitute for
production-storage acceptance.

## Remote RC hardware validation — 2026-09-26

The bounded remote validation report is
`docs/hardware/pi5_rc_hardware_validation_2026-09-26.md`.

- [x] Validate the full native libdrm/Wayland build on the Pi with
  `-Wall -Wextra -Wpedantic -Werror`, including KMS probe, DRM lease support,
  and both native self-tests.
- [x] Run the full Python test suite under Pi Python 3.13.5: `211 passed`;
  compileall, shell syntax, and the safe preflight fixture config also pass.
- [x] Run exactly one corrected HDMI-A-2-only 300-frame trace with the
  corrected kernel/callback/realtime/frame/buffer/photodiode schema;
  connector 42 and lease objects `[42,93,104,666]` completed `300/300` with
  contiguous sequences, zero mismatches, and `restored=true`.
- [x] Verify `DRM_CAP_TIMESTAMP_MONOTONIC=1`, labwc continuity, HDMI-A-1
  compositor continuity, and clean lease release.
- [x] Resolve both live IMX708 cameras from stable topology identities to
  unique numeric rpicam selectors; both one-second opens pass and duplicate
  identities fail closed.
- [x] Run the operator preflight and five hardware-free simulations/session
  inspections on Pi Python 3.13.5.
- [x] Run one short `/tmp`-only leased production-renderer plus dual-camera
  integration smoke with clean camera/display exit and restoration.
- [ ] Accept production storage: the experiment SSD is absent, and no mount,
  write probe, endurance test, or SD-card fallback was used.
- [ ] Accept physical/optical display timing, GPIO/reward/lick behavior, or a
  behavioral session; these remain deferred until physical presence.

### Remote integration follow-up — 2026-09-26

- [x] Validate a clean local package install in an isolated Pi Python 3.13.5
  venv without `PYTHONPATH` dependence; validate the CLI, config, preflight,
  dry-run, five simulations, and session inspection.
- [x] Validate the production KMS renderer on real HDMI-A-2/connector 42 for
  420 synthetic frames covering gray, distinct assets, repeats, transitions,
  and final gray; no visual acceptance is claimed.
- [x] Exercise six bounded real `LocalCameraSupervisor` dual-camera cycles
  with RAM-backed output growth, manifests, stop/reap, and no residual workers.
- [x] Exercise one controlled required-camera failure and one SIGINT cleanup
  at the real display/camera component boundary; required-camera failure and
  interruption were not promoted to unified-runtime acceptance.
- [x] Exercise ten short HDMI-A-2 lease/release iterations with restoration,
  HDMI-A-1 continuity, and labwc/process checks.
- [x] Exercise twenty short composed display-plus-camera resource sessions;
  RAM, load, temperature, throttling, and process cleanup remained bounded.
- [x] Complete the read-only GPIO/reward source audit and Monday checklist in
  `docs/hardware/pi5_gpio_reward_preflight_2026-09-26.md`.
- [ ] Validate a real telemetry loopback against the monitor: the checkout now
  has a local UDP transport boundary and bounded in-memory test sink, but the
  production unified session runner is not yet wired to it and the monitor-Pi
  path remains unvalidated.
- [ ] Integrate the real display/camera components into a production session
  state writer and preserve interrupted partial artifacts.
