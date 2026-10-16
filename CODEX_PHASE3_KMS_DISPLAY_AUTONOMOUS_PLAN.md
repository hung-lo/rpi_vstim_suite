# Codex Next Work Plan — Canonical Phase 3 KMS/DRM Standalone Probe and Display Backend

Repository: `rpi_vstim_suite`

Authoritative plan:
`RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md`

Current commit:
`f298987 Add SSD-independent Pi 5 display groundwork`

Current verified state:
- Canonical Gate 2 remains incomplete only because production storage validation is deferred until the experiment SSD is physically attached.
- The user explicitly authorized SSD-independent display work to continue.
- Provisional display mapping:
  - `HDMI-A-1` = stimulus display
  - `HDMI-A-2` = camera-preview display
- Keep the mapping configurable and easy to swap later.
- `/dev/dri/card1` is currently the VC4 display device on the audited Pi.
- `HDMI-A-1` preferred/active mode is approximately `1024x600@59.82` and also supports `1280x720`.
- `HDMI-A-2` is connected/active at approximately `1024x600@59.82`.
- Two local IMX708 cameras are present.
- Production SSD is currently absent.
- 91 tests passed at the end of the previous work.
- No production Phase 3 backend has yet been completed.

The user may be away from the PC. Work autonomously through all safe Phase 3 display milestones below.

If a step is blocked by physical user input, record the blocker and continue to the next safe software task.

Do not wait for the SSD.

## Hard boundaries

Do NOT:
- modify `/etc/fstab`
- format/repartition storage
- substitute the Pi SD card as production recording storage
- change boot configuration
- reboot unless absolutely required and clearly justified by the authoritative plan
- disable the preview display globally
- modify the reference repositories
- modify `rpi_rig_monitor`
- actuate reward/water/suction
- toggle unknown GPIO
- run production behavioral sessions
- perform final dual-camera + display + GPIO integrated acceptance
- claim storage readiness
- merge to `main`

Keep all display changes reversible and short-duration during hardware tests.

## Milestone 1 — Preserve current work

Before new implementation:
- verify `git status`
- verify branch name
- inspect `git log -3 --oneline`
- ensure commit `f298987` is present
- if the branch has an upstream and normal push is safe, push the current branch
- do not merge

Record the branch/commit used for all subsequent work.

## Milestone 2 — Review canonical Phase 3 requirements

Read the entire Phase 3 section of:
`RPI5_UNIFIED_VSTIM_CODEX_IMPLEMENTATION_PLAN.md`

Also review:
- `IMPLEMENTATION_STATUS.md`
- `docs/hardware/pi5_phase2_audit_2026-09-25.md`
- current display abstractions
- current `hardware display-probe`
- all display-related tests

Write an internal checklist of:
- requirements already satisfied by `f298987`
- requirements still missing
- what requires real Pi validation
- what can be tested in WSL/CI

Do not assume previous groundwork is equivalent to the canonical Phase 3 gate.

## Milestone 3 — Implement a standalone native KMS/DRM probe

Implement the smallest production-relevant standalone KMS probe necessary to prove:
- configured DRM device/connector can be opened
- configured connector can be resolved from read-only discovery
- chosen mode can be selected intentionally
- a framebuffer/buffer can be presented using native DRM/KMS
- page flips can be scheduled
- page-flip/vblank completion can be timestamped
- resources can be released cleanly
- original display state can be restored or safely relinquished

Important:
- use `HDMI-A-1` as the provisional stimulus connector
- keep connector selection configurable
- do not hard-code `/dev/dri/card1` as a universal constant
- discovery must still resolve the device dynamically
- do not silently fall back to HDMI-A-2
- fail closed if the configured stimulus connector is absent/disconnected
- keep HDMI-A-2 outside the stimulus backend unless explicitly required

Prefer direct Linux DRM/KMS primitives or a minimal well-supported dependency compatible with Pi 5 / Debian Trixie.

Do not introduce legacy framebuffer, WiringPi, `/dev/vcio`, or Pi-3/Pi-4-only assumptions.

## Milestone 4 — Exact timing instrumentation

The standalone probe must record timing sufficient to assess display behavior.

At minimum capture:
- requested mode
- actual selected mode
- nominal refresh rate
- monotonic timestamp before submit
- page-flip/vblank completion timestamp
- frame index
- inter-frame interval
- missed/deferred flip indication where detectable
- startup/shutdown timing
- connector/device identity

Use monotonic/high-resolution clocks and lightweight logging.

Do not claim photodiode-equivalent validation from software timestamps alone.

Add analysis helpers/tests that compute:
- median frame interval
- p95/p99 interval
- min/max
- number of intervals outside a documented tolerance
- estimated refresh rate

## Milestone 5 — Short real-Pi KMS smoke test

Deploy only the minimal code needed for the standalone probe to the experiment Pi.

Run a short no-mouse test on the provisional stimulus display.

Use a simple deterministic pattern:
- alternating full-screen values, or
- a clearly visible frame counter/checker
- optional small photodiode patch region if already part of the architecture

Keep duration short.

Do not involve cameras, GPIO, reward hardware, or telemetry unless harmless logging requires it.

Record:
- actual connector selected
- actual mode selected
- number of frames
- timing statistics
- missed page flips
- whether the preview display remained usable
- whether cleanup/restoration succeeded

If another compositor/session owns the display:
- diagnose the current ownership/session state
- document the exact conflict
- do not make broad system changes automatically

## Milestone 6 — Implement the real display backend

Once the standalone probe is proven, implement the real KMS/DRM display backend behind the existing abstraction.

Requirements:
- fake backend remains usable on WSL/macOS/CI
- backend selection remains explicit
- real backend is import-safe on non-Pi systems
- resource acquisition/release is deterministic
- connector/mode selection uses existing config
- refresh mismatch policy is respected
- no silent connector fallback
- cleanup is best-effort
- terminal runtime state remains correct on display failure
- display setup failure must not leave partially initialized state

Expose timing information required later by protocol/session logs.

Do not yet integrate complex preview rendering on HDMI-A-2.

## Milestone 7 — Photodiode patch plumbing

Implement software plumbing needed for a photodiode patch.

Requirements:
- patch location/size configurable
- patch state determined by frame plan/display frame state
- deterministic relationship between patch state and frame index
- logging records intended patch state
- no duplicated protocol-specific implementation

This is software plumbing only.

Actual photodiode timing acceptance remains a hardware measurement task.

Add unit tests.

## Milestone 8 — Display mode and refresh policy tests

Add hardware-independent tests for:
- configured connector found
- configured connector missing
- configured connector disconnected
- multiple connected displays
- stimulus/preview role separation
- supported requested mode
- unsupported requested mode
- exact refresh required and unavailable
- nearest-refresh policy where allowed
- no accidental selection of preview display
- reordered DRM cards/connectors
- invalid EDID/mode information
- cleanup after partial initialization failure

Use sanitized real audit fixtures where appropriate.

## Milestone 9 — KMS failure injection

Exercise failure at:
- DRM open
- connector resolution
- mode selection
- framebuffer/buffer creation
- first modeset
- first page flip
- mid-run page flip
- event wait
- shutdown/restore
- logging

Requirements:
- no unbounded retry loops
- cleanup continues after one cleanup failure
- runtime records failure where possible
- no transition back into TASK after terminal failure
- no test requires real hardware

## Milestone 10 — Short deterministic hardware timing run

If the standalone probe and backend work safely, run a slightly longer but still short no-mouse timing validation on the Pi.

Record:
- requested vs actual mode
- frame count
- interval summary
- outliers
- missed flips
- startup/cleanup behavior
- whether HDMI-A-2 remained available

Do not run integrated cameras/GPIO yet.

If timing is unstable, investigate and document before moving on.

## Milestone 11 — Documentation and status

Update:
- `IMPLEMENTATION_STATUS.md`
- `docs/hardware/pi5_phase2_audit_2026-09-25.md` only if clarification is needed
- add a dedicated Phase 3 KMS/DRM bring-up report under `docs/hardware/`
- relevant developer documentation

Clearly distinguish:
- verified real-hardware KMS behavior
- software-only tested behavior
- provisional HDMI role assumption
- deferred photodiode validation
- deferred SSD/storage validation
- deferred integrated dual-camera load testing

Do not mark the full experiment stack accepted.

## Milestone 12 — Validation

Run:
```bash
python -m pytest -q
python -m compileall -q src tests
git diff --check
```

Run Ruff according to project config.

Run shell syntax checks.

Run all five protocol simulations again.

If practical, run import tests on the Pi's Python 3.13 environment.

Record:
- exact test count
- exact failures
- changed-file Ruff result
- full Ruff status
- simulation status
- Pi smoke/timing results

Do not hide pre-existing lint findings.

## Milestone 13 — Commit discipline

Create coherent commits.

Suggested separation:
1. standalone KMS probe + tests
2. production display backend + tests
3. photodiode/timing plumbing + tests
4. docs/status/hardware report

Fewer commits are fine if tightly coupled.

Do not merge to `main`.

Push the branch if normal branch push is safe and already configured.

## Stop conditions

Stop if:
- display ownership requires a boot/session architecture decision from the user
- boot configuration changes appear necessary
- a reboot becomes necessary
- physical confirmation of HDMI mapping is required for correctness
- a test would risk reward/GPIO hardware
- remaining work is only photodiode, storage, or integrated-load validation

Otherwise continue through safe Phase 3 display milestones autonomously.

## Final report

At completion report:
1. branch and commits
2. KMS/DRM implementation summary
3. real Pi connector/mode actually used
4. standalone probe result
5. display backend result
6. page-flip/vblank timing statistics
7. photodiode software-plumbing status
8. cleanup/restoration result
9. preview-display impact
10. test counts
11. simulation results
12. lint status
13. unresolved hardware blockers
14. exact items still requiring the user
15. explicit statement that storage and full integrated hardware acceptance remain incomplete
