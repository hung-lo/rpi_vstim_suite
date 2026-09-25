# Implementation status

## Phase 00 — source freeze and bootstrap

- [x] Read implementation plan.
- [x] Record source repository commits and migration ownership.
- [x] Add Python 3.13 package metadata and CLI skeleton.
- [x] Add TOML configuration dataclasses and validation.
- [x] Add fake display and simulated hardware boundaries.
- [x] Add session, lifecycle, provenance, event logging, and output skeletons.
- [x] Add protocol placeholders and compatibility wrappers.
- [x] Add read-only Pi 5 audit report.
- [x] Apply Phase 00 validation/reproducibility review fixes.
- [x] Define two local camera identities in the Phase 00 schema.
- [x] Merge Phase 00 into the overnight branch without starting Phase 01.
- [ ] Authenticate a future deployment workflow with a stored, approved SSH key.

### Target inventory findings

The target passed the identity, OS, Python, time-sync, device-node, and
thermal inventory checks. `/mnt/hd` is not mounted, and the connected HDMI
mode/connector choice still needs physical confirmation. No assignment/state
files were accessed and no target files or services were changed.

## Overnight software groundwork

- [x] Simulated lifecycle orchestration with manifests, events, failure paths,
  deterministic seeds, and safe cleanup.
- [x] Deterministic frame plans with phase, trial/sequence IDs, photodiode
  intent, and stable serialization.
- [x] Natural-image selection and scheduling with explicit plain/camera
  compatibility profiles.
- [x] Reward-conditioning assignment, acquisition/reversal state, 8:3:1
  blocks, exact production 198/22 reward outcomes, and water safeguards.
- [x] Protocol-neutral bounded telemetry contract.
- [x] Independent metadata-only fake local camera state for two cameras.
- [x] End-to-end simulated acceptance tests.
- [x] Pure drifting-grating, retinotopy, and spout-training plans with
  deterministic golden tests.
- [x] Overnight compatibility, resource-budget, and fault-injection coverage.

## Explicitly deferred

Real experiment execution, GPIO, DRM/KMS, camera acquisition, UDP send, asset
conversion, reward actuation, and Pi modification remain deferred. The
expanded audit script has not been rerun because the Pi is not reachable from
this Mac; that is deferred hardware validation.
Phase 01 has not started.
