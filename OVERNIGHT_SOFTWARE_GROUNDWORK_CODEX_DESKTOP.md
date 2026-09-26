# Overnight Software Groundwork — Codex Desktop

## Purpose

Use this branch for an unattended, hardware-independent implementation run after Phase 00 has been reviewed and merged.

This is **software groundwork only**. Do not claim that later hardware-gated phases in `RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md` are complete. The authoritative plan and its physical Pi 5 gates remain in force.

## Repository / branch

Work only in:

`rpi_vstim_suite`

Recommended branch:

`codex/overnight-software-groundwork`

Start from the reviewed `main` branch after Phase 00 is merged.

## Governing specification

Read the entire:

`RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md`

It is authoritative.

Architecture that must be preserved:

- one experiment Raspberry Pi 5
- stimulus display, GPIO/lick/reward, logging, telemetry, and two local cameras on that Pi
- `rpi_rig_monitor` remains a separate repository and separate monitor Pi
- no second/remote camera Pi
- no SSH camera control or cross-Pi camera video transfer
- Python `>=3.13,<3.14`
- bounded memory/resource usage, especially because the experiment Pi has 2 GB RAM
- real hardware implementations and physical acceptance remain deferred

Ponytail is enabled. Prefer simple, explicit implementations, but never simplify away experimental correctness, reproducibility, safety checks, timing semantics, compatibility requirements, or tests.

## Reference repositories

The following repositories are **read-only reference implementations**:

- `rpi_visual_stimuli`
- `vstim_natural`
- `vstim_natural_img_reward`
- `rpi_rig_monitor`

Do not modify them.

Use the exact frozen source commits recorded in the repository source-baseline/migration documentation whenever possible.

If a reference repository is unavailable locally and cannot be accessed safely, do not invent its behavior. Continue with milestones that do not depend on that source and record the blocked item in `OVERNIGHT_REPORT.md`.

## Critical rule about phases

The authoritative plan contains hardware gates. This overnight run may implement **pure software components that will later support those phases**, but it must not:

- mark Pi audit/KMS/GPIO/camera hardware gates as passed
- claim natural-image or reward protocols are production-ready
- change `IMPLEMENTATION_STATUS.md` to imply hardware acceptance
- skip required future physical validation

Use the term **software groundwork** in commits and documentation where needed.

---

# Milestone A — Complete simulated runtime orchestration

Build the shared non-hardware runtime far enough to execute a complete fake session.

Implement or finish:

- session orchestration
- protocol selection/registry
- runtime service construction
- fake display wiring
- simulated GPIO/hardware wiring
- null/in-memory telemetry wiring
- fake local-camera service wiring
- lifecycle transitions
- clean completion
- interruption/failure handling
- session manifest/status updates
- event logging
- deterministic seed propagation
- source/provenance persistence

Requirements:

- imports must have no device/network side effects
- fake backends must be deterministic
- no real sleep is required unless explicitly testing elapsed-time semantics
- failure cleanup must leave simulated outputs safe
- a fake camera failure must not corrupt stimulus/session outputs

Add tests for normal completion, interruption, protocol failure, camera failure, telemetry failure/degradation, and cleanup.

### Milestone A gate

Run:

- full pytest
- ruff if available
- compileall/import checks
- CLI smoke tests
- at least one complete fake session

Commit separately with a descriptive message.

---

# Milestone B — Deterministic scheduling / event-plan layer

Implement the shared pure scheduling primitives needed by protocols.

Focus on data/planning, not rendering.

Include only abstractions justified by the legacy protocols, such as:

- frame-count / refresh-based durations
- deterministic local RNG usage
- trial IDs and sequence IDs
- explicit PRE/TASK/POST plan representation where useful
- stimulus/event plan structures
- photodiode state/event representation
- planned versus observed timestamp fields
- serialization suitable for golden tests
- no dependence on wall-clock timing during plan construction

Do not create a large generic framework if simple dataclasses/functions are sufficient.

Add tests for:

- deterministic replay from seed
- no use of process-global random state
- integer frame-duration behavior
- serialization stability
- edge cases around empty/single-item schedules where relevant

### Milestone B gate

Run tests/checks and commit separately.

---

# Milestone C — Natural-image pure logic migration

Port only the hardware-independent natural-image behavior from the frozen `vstim_natural` reference.

Preserve documented behavior including, where applicable:

- image discovery/selection
- reproducible ordering
- no-adjacent-repeat behavior
- repetition handling
- jittered ITIs represented using integer display-refresh counts
- initial/final gray periods
- both documented final-ITI compatibility profiles
- selected-image table/plan metadata
- photodiode plan semantics
- natural-image session metadata

Do not implement KMS/DRM rendering.

Do not implement real camera recording.

Camera use at this layer should only produce requested camera-service intent/metadata for the shared local dual-camera service.

Create golden/deterministic tests from legacy behavior where the source supports them.

If exact legacy behavior cannot be established from the source, document the uncertainty rather than guessing.

### Milestone C gate

Run tests/checks and commit separately.

---

# Milestone D — Reward-conditioning pure behavioral logic

Port only pure/non-hardware reward-conditioning behavior from the frozen `vstim_natural_img_reward` source.

Preserve established semantics including:

- permanent mouse/image assignment behavior
- persisted assignment/state model
- acquisition/reversal phase state
- 8:3:1 block construction
- 90% reward schedule semantics
- reward/omission accounting
- trial outcome representation
- water-limit/safeguard logic that can be represented without actuating hardware
- session completion/incomplete-state semantics
- reproducible randomization

Do not actuate GPIO.

Do not open lick hardware.

Use simulated lick/reward events for tests.

State-writing tests must use temporary directories and must never touch real lab assignment/state paths.

Add golden/regression tests around the most important legacy schedules and state transitions.

### Milestone D gate

Run tests/checks and commit separately.

---

# Milestone E — Protocol-neutral telemetry contract

Implement the software-side telemetry contract needed by `rpi_rig_monitor`, without requiring the monitor Pi.

Goals:

- canonical protocol-neutral event/message schema
- version field
- session identity
- protocol identity
- lifecycle/state
- current trial/stimulus fields where applicable
- lick/reward/omission counters where applicable
- camera status summary
- error/degraded state representation
- serialization/deserialization tests
- in-memory/null publisher for integration tests

Preserve existing monitor compatibility where documented by the source repositories.

Do not make monitor availability a requirement for successful experiment execution unless a config explicitly marks telemetry required.

Do not send real network packets in the overnight integration tests.

### Milestone E gate

Run tests/checks and commit separately.

---

# Milestone F — Local dual-camera supervisor model with fake workers

Implement the non-hardware camera control/state layer only.

Do not access V4L2/libcamera/rpicam devices.

Model two independently configured local cameras with:

- logical camera ID
- role
- stable configured identity
- required/optional status
- per-camera state
- requested start
- ready
- recording
- stop
- completed
- failed/degraded
- output manifest metadata

Use fake workers/services for tests.

Requirements:

- no SSH
- no remote paths
- no cross-Pi transfers
- bounded queue/state behavior
- one camera failure is represented independently from the other
- required-camera failure can fail startup/session according to config
- optional-camera failure degrades explicitly
- no camera code owns GPIO or reward state
- no full-frame fake payloads are needed; simulate metadata/state only

Do not hard-code `/dev/video0` or `/dev/video1`.

Do not resolve physical devices yet.

### Milestone F gate

Run tests/checks and commit separately.

---

# Milestone G — End-to-end simulated experiment acceptance

Wire the completed software groundwork together.

The goal is to execute complete simulated sessions on the development machine using:

- fake display
- simulated GPIO/lick/reward
- two fake local cameras
- null/in-memory telemetry
- real session/config/provenance/event output machinery
- real pure protocol planning logic

Exercise at minimum:

1. natural-image simulated session without cameras
2. natural-image simulated session with both fake cameras
3. reward-conditioning simulated session with deterministic simulated lick/reward outcomes
4. interrupted session
5. required-camera startup failure
6. optional-camera degradation
7. telemetry unavailable but optional
8. deterministic replay with the same seed

Verify:

- expected session files are written
- seeds/source commit are retained
- outputs are deterministic where intended
- lifecycle terminal states are correct
- no real device/network access occurs
- cleanup runs on failures
- no unbounded queues or giant in-memory image/video payloads were introduced

If the CLI is ready, provide a clear dry-run/simulation invocation for the representative protocols.

Do not pretend simulated timing proves physical onset/timing.

### Milestone G gate

Run the full test suite and all available static/import checks.

Commit separately.

---

# Final overnight self-review

After all completed milestones:

1. Run the complete test suite.
2. Run ruff if available.
3. Run compileall/import checks.
4. Run representative end-to-end simulated CLI sessions.
5. Inspect `git status`.
6. Inspect the full branch diff from `main`.
7. Search for accidental real-hardware/network access in import paths/tests.
8. Search for new SSH/remote-camera assumptions.
9. Search for hard-coded `/dev/video0` or `/dev/video1`.
10. Search for unbounded queues/caches.
11. Search for TODO/FIXME placeholders on exercised paths.
12. Confirm no real reward/water command can execute.
13. Confirm no hardware gate was marked passed.
14. Confirm `main` was not modified/merged.

Create:

`OVERNIGHT_REPORT.md`

It should summarize:

- milestones completed
- commits created
- tests/checks and exact results
- legacy behaviors ported
- uncertainties/deferred items
- anything blocked by unavailable source repositories
- anything requiring Pi 5 hardware validation
- risks to review in the morning

Commit the report as the final overnight commit.

---

# Stop / failure rules

Do not spend the entire run retrying one blocker.

If a milestone is blocked:

- document the blocker
- preserve the last passing state
- commit only coherent completed work
- proceed to a later milestone only if it does not depend on the blocked work

Do not guess experimental semantics.

Do not weaken tests to make them pass.

Do not delete/overwrite legacy assignment or state data.

Do not modify the four reference repositories.

Do not modify the Raspberry Pi.

Do not install/configure system services.

Do not implement real KMS/DRM, GPIO, camera capture, or reward actuation.

Do not merge to `main`.

At the end, stop and report the branch/commits rather than continuing into hardware work.
