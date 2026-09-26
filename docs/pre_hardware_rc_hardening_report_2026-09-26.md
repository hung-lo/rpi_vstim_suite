# Pre-hardware release-candidate hardening report

Date: 2026-09-26. This report covers the software-only run on
`codex/pre-hardware-rc-hardening`.

## 1. Start and final commits

The required parent was `15cd7abc5a147b58d3d355b07f0f6ae675689021` on
`codex/phase4-deep-integration`. The reviewed implementation HEAD before this
report was `9dc1f86` and was pushed to
`origin/codex/pre-hardware-rc-hardening`. The report is committed separately
after final review. No prior reviewed history was squashed.

## 2. Architecture findings

The audit maps configuration, CLI, five protocol planners, asset discovery and
preparation, bounded frame transport, fake/KMS display ownership, native DRM
bridge, stable camera identity and subprocess supervision, storage/session
lifecycle, telemetry, GPIO/reward contracts, resource budgets, provenance,
timing analysis, tests, scripts, and documentation. Ownership is explicit
through `RuntimeServices`; the virtual rig exercises the in-memory sequence
adapter and real subprocess camera boundary.

## 3. Test-gap findings

Local `coverage`/`pytest-cov` was unavailable, so no percentage is claimed.
Targeted gaps were closed for future/corrupt artifacts, camera startup/stall/
kill paths, storage permission/space/fsync/collision/path replacement, seeded
determinism, session digests, preflight output, and virtual lifecycle cleanup.
Hard power-loss recovery and hardware resource acceptance remain deferred.

## 4. Linux native build result

Docker, Podman, libdrm, Wayland, and Python 3.13 were unavailable on this Mac.
The portable `kms_frame_selftest` compiled and ran with
`-Wall -Wextra -Wpedantic -Werror`. The full Linux command was attempted and
correctly stopped at missing `drm.h`; no DRM device was opened. A reproducible
Linux build script and GitHub Actions job were added.

## 5. CI result and design

`.github/workflows/native-linux.yml` uses Ubuntu, Python 3.13, apt-installed
native headers, editable package installation, pytest, compileall, TOML parse,
shell syntax, and the native build script. Heavy soak campaigns are not in
default CI; they remain explicit operator commands. The job has no hardware or
secret requirement.

## 6. Virtual-rig implementation

`virtual-run` composes configuration, synthetic assets, session outputs,
preflight metadata, resource summary, real subprocess cameras, a bounded
sequence display adapter, simulated hardware, bounded telemetry, cleanup,
finalization, and `inspect-session`. Faults can be injected at metadata,
storage, producer, display, finalization, and cleanup boundaries.

## 7. Camera emulator results

The emulator supports normal, delayed-startup, immediate failure, no output,
zero output, no-growth/stall, stderr, SIGTERM-ignore, delayed exit, truncated
output, and seeded failure. Manual mode results were: normal COMPLETE;
delayed-startup COMPLETE; fail/no-output/zero-output FAILED; stderr COMPLETE;
ignore-terminate CLEANUP_FAILED with forced kill/reap; delayed-exit and
truncated COMPLETE; seeded-failure with seed 1 FAILED and seed 0 COMPLETE.
The short virtual stall run completed before its 30-second stall deadline;
growth-then-stall deadline behavior is covered by the supervisor test suite.

## 8. Storage fault matrix

Software fault coverage includes permission denial, mount/production-root
rejection, expected-device mismatch, low free space, write/fsync probe failure,
directory collision, symlink/path replacement, and incomplete-marker retention.
Atomic metadata writes and finalization retain failure state; there is no silent
fallback to `/`, home, `/tmp`, the Mac filesystem, or the Pi SD card.

## 9. Crash-consistency matrix

The standalone campaign exercised eight boundaries: asset-manifest creation,
session metadata write, storage-low-space, producer start, producer mid-session,
finalization, cleanup, and interruption. Results were FAILED for the first six
failure injections, CLEANUP_FAILED for cleanup, and INTERRUPTED for interruption.
Each session remained inspectable; repeated inspection returned the same report;
none was falsely COMPLETE.

## 10. Schema and version audit

Durable JSON artifacts now carry explicit versions for session manifest,
provenance, config, plan, preflight, cache, assets, display rows/summary,
resource summary, and camera manifest. Readers reject malformed and future
versions. `inspect-session` detects corrupt streams, summary count mismatch,
missing recorded camera output, orphan temporary files, and manifest/final
status disagreement.

## 11. Reproducibility campaign

`500` paired cases passed: `100` each for natural images, reward conditioning,
spout training, drifting gratings, and retinotopy. Plan and asset-manifest
digests matched for every pair across varied seeds and configuration labels.
The campaign exposed reward seed 133; the planner now uses a bounded seeded
greedy fallback when randomized shuffling cannot find a valid non-repeating
block.

## 12. Long virtual-session soak

`10,000` sessions completed in `350.381s`, all with terminal state COMPLETE.
Thread delta was `0`, file-descriptor delta was `0`, and the Linux child-process
delta probe was unavailable on this Mac. Tracemalloc peak was `6,454,267` bytes,
peak RSS was `26,542,080` KB as reported by macOS, and temporary output was
`117,537,780` bytes before cleanup.

## 13. Frame stress

The realistic asset campaign consumed and produced exactly `100,000` logical
frames with capacity `16`, peak occupancy `16`, and `0` underruns. It performed
`6` decodes, `6` renderer payload allocations, `7` source reads, and `7` SHA
calculations. Repeated content remained deduplicated and no per-logical-frame
full payload allocation occurred.

## 14. Randomized concurrency stress

The seeded state-machine campaign passed `5,000` seeds and `5,000` simulated
sessions. Transport operations included put/get/finish/abort and each run
asserted the capacity invariant. Camera supervisor randomized behavior was
covered by deterministic subprocess torture tests; no orphan process remained.

## 15. Telemetry stress

`100,000` messages were published to a capacity-256 in-memory sink. Exactly
`256` were retained and `99,744` were dropped deterministically. No network
telemetry was opened and no frame payload was placed in the bounded sink.

## 16. Protocol parity and golden coverage

All five protocols have golden coverage. Natural images preserve seeded image
selection, repetition, ITIs, frame counts, and phase boundaries. Reward
conditioning preserves `500` events, `220` eligible presentations, and `198`
scheduled rewards. Spout training has a seeded boundary fixture of `9` events,
`1,716` frames, and `4` reward events. Drifting gratings and retinotopy retain
seeded ordering, photodiode intent, and frame/direction invariants. Intentional
differences remain documented in `docs/source_parity_matrix.md`.

## 17. Full-session golden digests

Timestamp/path-free behavioral digests now include schema versions, plan,
selected assets, display metadata, event order, reward decisions, and final
state. Fixed digest fixtures cover one representative deterministic session for
each of the five protocols and are checked by regression tests.

## 18. Packaging clean-environment result

The clean temporary venv used Python `3.12.4`. `pip install -e .` without
network failed while resolving the declared build dependency `setuptools>=68`;
the no-build-isolation attempt failed because the clean venv had no setuptools;
the system editable install reached and reported the intended metadata gate:
`Package 'rpi-vstim' requires a different Python: 3.12.4 not in '<3.14,>=3.13'`.
The checkout remained importable through the documented `src` layout and all
five CLI simulations, virtual-run, inspect-session, preflight, help, and
version checks passed.

## 19. Python 3.13 result

No local Python 3.13 interpreter was available. Code was audited for pathlib,
dataclass/enum serialization, subprocess/signal cleanup, typing, and temporary
file behavior. CI is configured to run the target interpreter. No system Python
was installed.

## 20. Leak audit

The reusable leak snapshot records Python threads, portable file descriptors,
and Linux `/proc` child counts when available. The 500-iteration lifecycle
campaign produced `400 COMPLETE` and `100 INTERRUPTED`, with thread and FD
deltas both zero. The 50-session subprocess virtual campaign inspected all
sessions and found no orphan camera process.

## 21. Operator preflight status

Readable preflight now reports protocol, frames, duration, asset status and
digest, estimated RAM/storage, camera roles and stable identities, display
requirements, production-root requirements, and unexercised hardware gates.
JSON output remains available. It never acquires hardware.

## 22. Session inspector status

`inspect-session` returns JSON or readable text, uses nonzero exit status for
corrupt artifacts, and is read-only by default. It reports COMPLETE,
INTERRUPTED, FAILED, CLEANUP_FAILED, degraded camera state, incomplete markers,
missing outputs, schema errors, orphan files, and final-status inconsistencies.

## 23. Next-lab runner status

`scripts/next_lab_acceptance.sh --dry-run` prepares safe Pi-side environment,
native build, display probe/lease/300-frame trace, camera enumeration, SSD
inspection, storage preflight, and session inspection commands. `--write-heavy`
is an explicit operator opt-in. The runner never formats disks, changes fstab,
reboots, touches GPIO, or delivers reward.

## 24. Exact fast-test result

Final command: `python -m pytest -q` — **209 passed in 12.91s**.

Additional passing checks: `python -m compileall -q src tests scripts`,
`bash -n scripts/*.sh ci/*.sh`, parsing `1` TOML example, `git diff --check`,
all five CLI simulations, and the fixed session-digest/golden tests.

## 25. Ruff and native limitations

Ruff was unavailable locally and is therefore not claimed. Docker and Podman
were unavailable. The portable C frame self-test passed warning-clean; the
full libdrm/Wayland build is deferred to Linux CI, and no real DRM runtime was
claimed. CI contains the native compile path and diagnostics.

## 26. Remaining hardware gates

No Pi SSH or hardware access occurred. Deferred gates are: HDMI-A-2 / connector
42 stimulus ownership; HDMI-A-1 / connector 33 camera-monitor behavior; real
camera topology and negotiated selectors; sustained dual-camera growth; SSD
identity, mount, throughput, and free-space acceptance; combined display plus
dual-camera plus SSD resource load; GPIO/reward/lick safety; and photodiode
timing. The recorded `105 long + 105 short` timing result and all historical raw
traces remain authoritative and were not rewritten or reinterpreted.

## 27. Merge blockers

There is no known software-only blocker in the reviewed branch. This branch is
not merged to `main`; production release remains blocked by the deferred
hardware gates above and by the unavailable local Python 3.13/Linux native
environment until CI or the Pi validates them.

## 28. Recommended exact next actions

1. Run the CI native Linux job and retain its compile/self-test logs.
2. On the Pi, connect the experiment SSD, record its identity, and reject the
   SD card, `/`, and temporary roots.
3. Run the documented preflight, connector 42 display probe/lease smoke, and
   corrected 300-frame trace; preserve raw output and the branch commit.
4. Resolve stable identities for both local cameras, then run one-camera,
   two-camera, and combined display/camera/SSD acceptance runs.
5. Inspect every session and record RAM, CPU/load, temperature/throttling,
   page-flip intervals, output growth, cleanup, config digest, and raw traces.
6. Defer GPIO/reward/lick and photodiode acceptance until pin/sensor ownership
   and the physical photodiode are available.

## Final summary

- Branch: `codex/pre-hardware-rc-hardening`
- Reviewed implementation HEAD: `9dc1f86` (report commit follows)
- Fast tests: `209 passed in 12.91s`
- Soak: `10,000 COMPLETE` in `350.381s`
- Stress: `500` repro pairs, `100,000` frames, `5,000` randomized seeds,
  `100,000` telemetry events, `50` virtual subprocess sessions, `500` leak iterations
- Linux native compile: portable frame self-test passed; full libdrm/Wayland build deferred to CI
- Software merge blocker: none known; no merge to `main`
- Hardware checks still required: display connectors/lease/timing, real dual-camera identity and growth, SSD acceptance/resource load, GPIO/reward/lick safety, and photodiode validation
