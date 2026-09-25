# Codex Long Autonomous Work Plan — Phase 2 Blocked / Hardware-Safe Groundwork

Repository: `rpi_vstim_suite`

Authoritative plan: `RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md`

Current canonical state:
- V2 architecture: one experiment Raspberry Pi 5, two local CSI cameras, separate `rpi_rig_monitor` Pi.
- Phase 0 and Phase 1 software groundwork are already substantially complete.
- Canonical Phase 2 audit has been performed.
- Gate 2 is NOT yet satisfied.
- Phase 3 KMS/DRM implementation MUST NOT begin until Gate 2 is explicitly satisfied.
- Current blockers are physical/configuration decisions that may require the user:
  - experiment SSD/device is absent; existing `/etc/fstab` references `/mnt/behavbox_ssd`
  - no verified `/mnt/hd` mapping
  - stimulus display has not yet been physically identified between connected `HDMI-A-1` and `HDMI-A-2`
  - storage throughput cannot be validated until the intended experiment storage is present

The user will be occupied with other work and may not be available to answer questions for a while.

## Operating rule

Keep working autonomously on useful **hardware-independent or read-only preparatory work**.

Do not sit idle merely because one task is blocked.

If a task requires a physical decision or unsafe/system-level action:
1. record the blocker,
2. skip that task,
3. continue to the next safe task.

Do NOT infer missing physical facts.

Do NOT cross the canonical Gate 2 boundary.

---

# Hard safety boundaries

While the user is away, DO NOT:

- start canonical Phase 3 production KMS/DRM backend implementation
- change boot configuration
- reboot the Pi
- format or repartition storage
- alter filesystem UUIDs
- modify `/etc/fstab`
- mount an ambiguous/unverified device
- select a stimulus display by guessing
- change groups, permissions, udev rules, or services
- install system packages unless absolutely necessary for an already-approved read-only diagnostic task
- toggle GPIO
- actuate reward/water
- actuate suction
- emit experiment TTLs
- run uncontrolled full-screen stimuli
- run long camera recordings
- run production behavioral sessions
- modify `rpi_rig_monitor`
- modify any frozen/reference repository
- implement remote/SSH camera control
- introduce assumptions that camera nodes such as `/dev/video0` or `/dev/video1` are stable identities
- merge into `main`

The current experiment architecture is:
- one Pi 5 for stimulus + GPIO + lick + reward + suction + logging + telemetry + two local cameras
- no second camera Pi
- monitor Pi remains a separate repository/system

---

# Milestone A — Preserve and commit the Phase 2 audit state

Review:

- `docs/hardware/pi5_phase2_audit_2026-09-25.md`
- `IMPLEMENTATION_STATUS.md`
- `git status`
- full diff against `main`

Ensure the documents clearly record:

- real Pi model/OS/kernel/Python
- two IMX708 camera identities/topology
- DRM connector findings
- diagnostic packages installed
- missing experiment storage
- existing `/etc/fstab` reference to `/mnt/behavbox_ssd`
- Gate 2 NOT satisfied
- Phase 3 NOT started
- no destructive/system configuration changes performed

Do not claim `/mnt/hd` is real or canonical without evidence.

If the current changes are clean, accurate, and contain no secrets or transient junk, make one coherent documentation/status commit.

Suggested commit concept:

`Document Phase 2 Pi 5 audit and readiness blockers`

Do not merge to `main`.

---

# Milestone B — Restore a complete local development/test environment

The previous run reported that `pytest` and `ruff` were unavailable locally.

Inspect repository packaging/configuration first:

- `pyproject.toml`
- optional dependency groups/extras
- lockfiles if any
- CI configuration
- existing development setup documentation

Use a repository-local Python environment rather than installing arbitrary system Python packages.

Prefer something like a repo-local `.venv` if that matches the project conventions.

Do not modify system Python.

Install only the project and its declared development/test dependencies.

Then run the complete hardware-independent validation suite, including at minimum:

```bash
python -m pytest -q
python -m compileall -q src tests
git diff --check
```

Run Ruff using the repository's declared configuration if available.

Also run all simulation/CLI acceptance paths for every currently implemented protocol.

Record:
- Python used
- environment location
- package install method
- exact test counts/results
- Ruff result
- any failing tests

Fix genuine software regressions discovered here, but do not weaken tests simply to make them pass.

Make coherent commits for real fixes.

---

# Milestone C — Audit implementation status against the canonical V2 plan

Read the entire canonical V2 implementation plan again.

Build an internal checklist mapping:

- canonical Phase 0 requirements -> current repo implementation
- canonical Phase 1 requirements -> current repo implementation
- canonical Phase 2 requirements -> completed / blocked / deferred
- later phases -> not started vs software groundwork already present

Update `IMPLEMENTATION_STATUS.md` if necessary so it does not confuse:
- previously used informal Phase 00/Phase 01 terminology
with
- canonical V2 Phase 0/1/2 numbering.

Preserve history.

Do not mark a hardware gate complete based solely on simulation.

Do not mark later canonical phases complete because pure planning logic exists.

---

# Milestone D — Strengthen read-only hardware discovery code

Without changing the Pi, review the repository's hardware audit/discovery tooling.

Goal: make future audits repeatable, structured, and testable.

Improve code/scripts where useful so they can collect and normalize:

## Pi/platform
- model
- OS release
- kernel
- architecture
- Python version
- RAM
- CPU temperature/throttling state where available

## Storage
- `lsblk -f`
- UUIDs
- filesystem types
- labels
- current mounts
- free space
- relevant `/etc/fstab` entries

Important:
- discovery code must distinguish:
  - configured path
  - currently mounted path
  - backing device
  - absent device
- no function should silently mount or modify storage

## DRM/KMS discovery
- DRM cards
- connectors
- status
- EDID identity
- modes
- preferred mode
- refresh rates
- current mode if discoverable

Important:
- do not assume `card0`
- do not assume connector numbering is stable across unrelated machines
- separate stable/semantic connector information from transient device paths

## GPIO discovery
- gpiochip devices
- chip labels
- line capabilities where safely readable
- no output changes

## Cameras
- libcamera/rpicam identities
- model
- sensor path/topology
- stable device identity information
- current transient device nodes where relevant
- supported modes where safely queryable

Add parsers and fixtures using captured/sanitized audit output.

Add unit tests for:
- multiple DRM cards
- multiple connected HDMI connectors
- absent storage
- unexpected/missing commands
- two identical-model cameras with different topology
- reordered transient `/dev/videoN` nodes

Normal unit tests must not require a Pi.

---

# Milestone E — Formalize stable dual-camera identity handling

Review the existing camera configuration and fake-camera implementation.

The code should clearly separate:

1. configured logical camera role, e.g. camera A / camera B
2. stable hardware identity/topology
3. runtime-resolved device/interface
4. recording output identity

Do not rely on `/dev/video0` or `/dev/video1` as persistent identities.

The two audited sensors are:
- IMX708 Noir
- IMX708 Wide Noir

Do not hard-code those model names as the only supported devices.

Use the audited information as fixtures/examples, not as a universal assumption.

Add tests for:
- identity resolution independent of enumeration order
- duplicate configured identities
- missing required camera
- missing optional camera
- ambiguous identity
- two cameras with the same broad model but different topology
- deterministic assignment of logical role to stable hardware identity
- runtime device renumbering

Keep fake camera behavior working on WSL/macOS/non-Pi CI.

Do not implement final production capture load behavior yet.

---

# Milestone F — Storage abstraction and path semantics

The audit revealed a likely mismatch between older planning language (`/mnt/hd`) and the real rig's existing `/mnt/behavbox_ssd` configuration.

Review all repository references to:

- `/mnt/hd`
- `/mnt/behavbox_ssd`
- storage root
- output root
- asset root
- camera recording root
- session root

Do not simply replace one hard-coded path with another.

Refactor, if needed, toward explicit configurable path roles.

Requirements:

- storage/output root should be configurable
- configuration validation should distinguish:
  - path absent
  - path exists but is not mounted as expected
  - path readable
  - path writable
  - insufficient free space
- simulation can use temporary/local paths
- Pi production config can specify the real path once verified
- no software component should implicitly mount storage
- no code should silently fall back from an unavailable experiment disk to the SD card for large production recordings

Add tests for these cases.

Document the policy.

Do not edit `/etc/fstab`.

---

# Milestone G — Resource-budget and bounded-buffer audit

The experiment Pi has only about 2 GB RAM and ultimately must handle:

- DRM/KMS visual presentation
- GPIO/lick acquisition
- reward/suction control
- telemetry
- session/event logging
- two local cameras
- disk writes

Perform a software/resource design audit.

Inspect for:
- unbounded queues
- unbounded lists
- full-frame Python queues
- accidental accumulation of frame objects
- telemetry buffering without fixed limits
- logging buffers without limits
- retry queues without limits
- large in-memory natural-image caches
- unnecessary copies

Where safe and clearly beneficial, improve bounded behavior.

Do not prematurely optimize working deterministic logic without evidence.

Add tests that demonstrate bounded queue/buffer behavior.

Update `docs/resource_budget.md` with:
- known assumptions
- simulated bounds
- what still requires real same-Pi load measurement later

Do not claim hardware acceptance from these software checks.

---

# Milestone H — Failure-injection and cleanup hardening

Expand hardware-independent failure tests around the runtime.

Cover failure at least in:

- session creation
- plan construction
- display setup
- camera startup
- one required camera missing
- one optional camera missing
- telemetry publisher failure
- event logging failure
- interruption/KeyboardInterrupt
- cleanup failure in one subsystem
- multiple cleanup failures
- output directory unavailable
- low-space preflight failure
- malformed persisted state
- corrupted assignment state
- incompatible config/protocol selection

Requirements:
- terminal lifecycle states must remain terminal
- cleanup is best-effort across all subsystems
- one cleanup exception must not prevent other cleanup
- failures should be recorded when possible
- simulation must never actuate real hardware
- no retry loop may become unbounded

Add regression tests.

---

# Milestone I — Determinism and provenance audit

Review all implemented protocols for reproducibility.

Confirm that session outputs preserve:

- master/session seed
- derived protocol seeds where applicable
- source commit
- config snapshot or immutable config representation
- protocol name/version/profile
- selected assets
- deterministic plan
- relevant assignment state
- event identifiers
- trial/frame/sequence identifiers

Test:
- same config + same seed -> same plan
- unrelated subsystem seeds do not perturb protocol selection
- camera enable/disable does not alter visual trial ordering unless explicitly specified
- telemetry enable/disable does not alter protocol schedule
- persisted reward assignment does not silently change across restart

Use stable JSON serialization where already intended.

Do not change legacy-compatible behavior without documenting why.

---

# Milestone J — Legacy/source conformance review

Use the frozen reference repositories as READ-ONLY sources only.

Do not modify them.

Verify the migrated pure logic against the frozen revisions recorded in `OVERNIGHT_REPORT.md`:

- `rpi_visual_stimuli`
- `vstim_natural`
- `vstim_natural_img_reward`
- `rpi_rig_monitor`

Focus on deterministic/software semantics, not hardware implementation.

Check at least:

## Natural images
- image discovery/order rules
- subset rules
- repetition semantics
- ITI/frame conversion
- profile differences
- metadata expectations

## Reward conditioning
- persistent mouse assignment
- acquisition/reversal phase semantics
- trial ratio/block logic
- omissions
- scheduled vs actually delivered reward semantics
- water/session limits

## Drifting gratings / retinotopy
- ordering
- timing representation
- repeat/block structure
- photodiode intent representation

## Telemetry
- backward-compatible fields expected by the monitor
- reserved-field collision protection
- lifecycle/state semantics
- camera aggregate status semantics

Where golden fixtures are generated by this new suite rather than independently copied/derived from legacy behavior, label them honestly as regression fixtures rather than legacy ground truth.

Add focused tests where useful.

---

# Milestone K — Config and CLI contract hardening

Review config schemas and CLI behavior.

Test and improve:

- explicit protocol/config mismatch rejection
- mutually exclusive or clearly defined precedence for singular vs plural camera CLI flags
- production vs simulation backend selection
- experimental config requirements
- invalid hardware backend values
- telemetry enabled/required consistency
- path role validation
- refresh-rate validation
- duplicate camera identity rejection
- missing required camera handling
- dry-run/simulated execution behavior

Avoid adding many new CLI flags unless they solve a demonstrated need.

Preserve backward compatibility when reasonable.

Document intentional breaking changes.

---

# Milestone L — Phase 3 KMS design package, but NO Phase 3 implementation

Prepare a detailed design/review package for the eventual KMS/DRM phase.

This is documentation/tests/interfaces only.

Do NOT implement the production backend.

Document:

- backend interface expectations
- discovery-to-selection flow
- how the configured stimulus display will be selected once physically identified
- desired mode selection rules
- exact vs approximate refresh handling
- page-flip/vblank timestamp strategy
- failure behavior
- cleanup/restore behavior
- photodiode patch integration point
- timing telemetry/logging fields
- standalone probe acceptance criteria
- no-mouse validation criteria
- what must be measured on real hardware

Identify which parts can be unit-tested with mocks.

Create mock fixtures/tests if useful, but do not open real DRM devices as a production backend.

Do not choose HDMI-A-1 vs HDMI-A-2 without the user's physical mapping.

---

# Milestone M — Camera production design package, but no final load acceptance

Prepare the production dual-camera design based on the V2 architecture and actual Pi audit.

Document:

- one worker/process per camera
- startup/shutdown supervision
- bounded buffering
- direct-to-disk strategy
- timestamp strategy
- filename/session linkage
- stable identity resolution
- required vs optional camera policy
- degraded session behavior
- storage-space preflight
- disk-write failure behavior
- worker crash behavior
- no expensive TASK-time transcoding unless later validated
- later same-Pi load-test matrix

Do not implement uncontrolled long recording while the user is away.

Software-only worker/supervisor logic may be improved using fake backends if it stays hardware-independent.

---

# Milestone N — Telemetry compatibility and failure isolation

Review telemetry implementation for:

- nonblocking experiment path
- bounded queue/buffer
- schema/version consistency
- monitor backward compatibility
- session/lifecycle state semantics
- dual-camera aggregate status
- counters
- timestamp fields
- reserved-field protection
- network failure isolation

Create tests showing:
- monitor unavailable does not block experiment runtime
- queue full behavior is bounded and defined
- malformed telemetry payload is rejected safely
- individual event publish failure does not corrupt experiment state
- telemetry disabled path is deterministic

Do not modify the monitor Pi or monitor repository.

---

# Milestone O — Full simulated acceptance matrix

Run an end-to-end simulated acceptance suite for every implemented protocol.

At minimum:
- natural images
- reward conditioning
- spout training
- drifting gratings
- retinotopy

For each:
- deterministic normal completion
- interruption
- required-camera failure
- optional-camera degradation where applicable
- telemetry unavailable
- output-path failure
- cleanup verification

Confirm generated session structure and manifests.

If runtime is short, run repeated deterministic simulations to catch state leakage.

Do not run real behavioral sessions.

---

# Milestone P — Documentation consolidation

Improve developer documentation so another developer can understand:

- architecture
- current canonical phase
- completed groundwork
- real audited Pi hardware facts
- unresolved Gate 2 blockers
- how to set up local development
- how to run tests
- how to run simulation
- how to run the read-only Pi audit
- how stable camera identities work
- storage-path policy
- what absolutely must not be done before Gate 2
- next physical actions required from the user

Archive obsolete temporary planning/review documents only if clearly superseded and if doing so does not remove useful history.

Do not delete the authoritative V2 plan.

---

# Work/commit policy

Work sequentially through the safe milestones above.

For each substantial milestone:

1. inspect existing code first
2. make the smallest coherent change
3. add/update tests
4. run relevant validation
5. inspect diff
6. make a coherent commit

Do not create noisy commits for trivial formatting.

Do not merge into `main`.

Do not rewrite shared Git history.

Do not push destructive changes.

If network access allows normal branch pushes and the branch is already configured, pushing ordinary commits is acceptable; otherwise leave them local and report them.

---

# When to stop

Continue working through safe milestones even if one item is blocked.

Stop only when:

- all safe milestones are complete, OR
- the remaining tasks require physical user input, destructive/system changes, or crossing Gate 2, OR
- a serious unexpected issue makes further changes unsafe.

Do not start canonical Phase 3 automatically.

---

# Final report

When finished, produce a concise but complete report containing:

1. commits created, in order
2. files changed
3. tests and exact results
4. simulation results
5. software bugs found/fixed
6. hardware-discovery improvements
7. camera identity improvements
8. storage-path/config improvements
9. resource/bounded-buffer findings
10. determinism/provenance findings
11. telemetry findings
12. documentation added/updated
13. unresolved Gate 2 blockers
14. exact physical actions still needed from the user
15. explicit statement that Phase 3 was not started

Also update `IMPLEMENTATION_STATUS.md` accurately.

Do not claim hardware gates are passed unless they were actually validated on the hardware.
