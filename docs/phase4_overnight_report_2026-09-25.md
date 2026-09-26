# Overnight Phase 4 software-groundwork report

Date: 2026-09-25
Execution host: Mac
Hardware access: none; no Pi login, SSH, camera, SSD, GPIO, photodiode, or
hardware test was attempted.

## 1. Branch and commits

Stage 1 completed and was pushed on `codex/phase-03-kms-display-ownership`:

- `a3b2a40` — `Fix Phase 3 v2 timing clock and build dependency`

Stage 2 was created from that reviewed Phase 3 HEAD with
`git switch -c codex/overnight-phase4-software-groundwork` and pushed upstream.
The overnight commits on this branch are:

- `2cde7a4` — `Add bounded natural-image frame preparation`
- `c0788c4` — `Harden camera storage and timing groundwork`
- `3317b71` — `Integrate bounded session and analysis outputs`
- final report commit containing this document

No commit was merged into `main`, squashed, or rewritten. The two user-provided
instruction files remained untracked and were not staged.

## 2. Natural-image frame source

Added an asset resolver and producer-side preparer with safe relative-path
resolution, SHA-256 identities, source metadata, explicit decode errors, RGB888
conversion, alpha compositing, and `stretch`, `fit_pad`, and `crop` policies.
Pillow is an optional `images` extra. Preparation is bounded by an observable
LRU cache and occurs before the native flip path.

## 3. Frame transport and sequence boundary

Added `NaturalImageFrameSource` and a bounded ordered
`BoundedFrameTransport` with explicit finish, abort, and backpressure behavior.
Plan events stream into prepared frames without preloading decoded images. The
native KMS path remains the validated bounded two-frame smoke transport; no
unvalidated native arbitrary-frame ABI was invented on the Mac.

## 4. Dual-camera supervisor

Added one independently supervised local process contract per camera, with
required/optional failure policy, bounded status records, startup/output-growth
deadlines, crash polling, terminate/kill stop cleanup, deterministic per-camera
output paths, and a camera manifest. The supervisor has no device access at
import time and tests use fake processes only.

## 5. Camera metadata and provenance

Camera schema and manifests now carry stable device identity, role, backend,
requested mode, codec/format, output naming policy, start/stop monotonic and UTC
timestamps, byte growth, exit status/reason, and verification state. The
capture command builder does not guess transient `/dev/videoN` nodes.

## 6. Storage preflight

Added fail-closed storage preflight for configured production roots. It checks
safe root policy, existence, directory type, mount state, writeability, free
space, estimated required bytes, and an optional expected-device identity hook.
It never mounts, formats, discovers, or silently falls back to the SD card,
home directory, `/tmp`, or `/`.

## 7. Session outputs

Session output now records preflight, cache, display, resource, selected-image,
camera, and final-status artifacts alongside the existing manifest, plan,
provenance, resolved configuration, and event log. Final status preserves
terminal lifecycle, degraded state, errors, and cleanup errors.

## 8. Resource bounds

Added parameterized estimates for two scanout buffers, prepared and natural
source caches, per-camera bounded queues, telemetry, logs, total estimated RAM,
and camera storage bytes per second. The helper is deliberately a configured
software bound, not a substitute for Pi measurements.

The authoritative combined-load baseline remains unchanged: approximately
1.2 GiB minimum available RAM, 45.0 C peak, load up to 1.38, and `throttled=0x0`.

## 9. Timing analysis

Added non-mutating flip-trace analysis for kernel timing, callback timing, frame
and sequence gaps, buffer/photodiode metadata mismatches, comparable-clock
dispatch latency, and paired long-then-short callback displacement. The
recorded 105-long plus 105-short pattern is preserved as historical evidence;
no raw trace was rewritten or reinterpreted by this Mac work.

## 10. Integration coverage

Coverage includes deterministic natural-image preparation, bounded cache and
transport behavior, plan-to-transport replay, missing-asset failure, camera
worker start/stop/crash/cleanup behavior, bounded status flow, storage gates,
resource estimates, session artifacts, timing classification, config parsing,
and all five simulation protocol entry points.

## 11. SSD validation checklist

Added `docs/ssd_hardware_acceptance_checklist.md` covering identity and mount
inspection, writable/free-space checks, bounded read/write testing, one-camera
and two-camera output growth, combined display/camera load, the corrected
300-frame leased trace, recovery, and explicit rejection of SD-card fallback.
This checklist remains deferred hardware validation.

## 12. GPIO/reward preparation

Added the software boundary document for one dedicated GPIO/reward worker with
safe inactive startup, bounded commands, explicit safe/shutdown states,
timestamped lick/reward events, water limits, and cleanup isolation. No pin
mapping or electrical behavior was guessed; actuation validation remains
hardware-gated.

## 13. Exact validation results

- `python -m pytest -q` — 156 passed.
- `python -m compileall -q src tests` — passed.
- `bash -n scripts/*.sh` — passed.
- TOML parse of all 9 files under `config/` — passed.
- `git diff --check` — passed.
- `make -C native/kms_display kms_frame_selftest` — passed.
- `native/kms_display/kms_frame_selftest` — passed.
- Five simulations — all exited 0 and completed: `natural-images`,
  `reward-conditioning`, `spout-training`, `drifting-gratings`, and
  `retinotopy`.

## 14. Validation limitations

- `python -m ruff check src/rpi_vstim tests` could not run because Ruff is not
  installed in the Mac interpreter (`No module named ruff`).
- The full native DRM build remains unavailable on this Mac because libdrm
  development metadata/headers are absent (`libdrm.pc` and `drm.h`). The
  portable native frame self-test passed.

## 15. Deferred hardware gates

Actual IMX708 identity/mode negotiation, camera output growth, SSD identity and
sustained writes, combined display plus dual-camera timing, GPIO/reward/lick
behavior, photodiode validation, final stimulus-screen validation, and native
Linux DRM acceptance remain deferred. The experiment SSD is not treated as
connected, and the Pi SD card is not treated as production-storage acceptance.

## 16. Scope confirmation

The recorded display assignment remains HDMI-A-2 / connector 42 for visual
stimuli and HDMI-A-1 / connector 33 for the camera monitor. The Phase 3
hardware results and historical raw traces were preserved. No Pi SSH or
hardware testing was attempted, no frozen reference repository was modified,
and Phase 01 was not started.
