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
- [ ] Authenticate a future deployment workflow with a stored, approved SSH key.

### Target inventory findings

The target passed the identity, OS, Python, time-sync, device-node, and
thermal inventory checks. `/mnt/hd` is not mounted, and the connected HDMI
mode/connector choice still needs physical confirmation. No assignment/state
files were accessed and no target files or services were changed.

## Explicitly deferred

No experiment execution, real GPIO, DRM/KMS, camera acquisition, UDP send,
asset conversion, reward logic, protocol scheduling, or Pi modification is
implemented in Phase 00. The expanded audit script has not been rerun because
the Pi is not reachable from this Mac; that is deferred hardware validation.
Phase 01 has not started.
