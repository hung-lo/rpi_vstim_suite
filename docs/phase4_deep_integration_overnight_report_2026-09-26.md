# Phase 4 deep-integration overnight report

## 1. Branches and commits

The run began on `codex/overnight-phase4-software-groundwork` at `4264c09`,
completed Stage 0 there as `99aebb3` (`Harden Phase 4 software groundwork`),
and created the required deep branch from that reviewed HEAD:
`codex/phase4-deep-integration`.

The reviewed implementation HEAD before the report commit was `d15b4cc`.
The report itself is the immediately following final commit. Deep-branch
commits are:

- `971b394` — `Add frozen source parity coverage`
- `c45cda4` — `Integrate bounded Phase 4 software boundaries`
- `c4f56f0` — `Extend Phase 4 campaign coverage`
- `d15b4cc` — `Add camera stall and forced-stop torture coverage`

The branch was pushed to `origin/codex/phase4-deep-integration`. There was no
merge to `main`. Phase 01 was not started. The three user-provided instruction
files remain untracked and were not committed.

## 2. Stage 0 review fixes

All 0A–0J corrections were implemented in `99aebb3`: condition-based frame
transport close/abort wakeups, immutable selected-asset manifests, no repeated
source hashing on cache hits, no unnecessary packed-frame copies, camera
shutdown/reap and stall semantics, unsafe storage fallback rejection,
streaming display results, generic timing validation, expanded resource-budget
accounting, and JSON serialization coverage.

## 3. Source-parity audit

Frozen repositories were read-only inputs at their recorded commits. Natural
image behavior is covered by a golden fixture for sorted selection, seed 777,
repetition order, no adjacent repeats, inclusive 42–60-frame ITIs, 30-frame
images, gray 127, and the crop/RGB compatibility profile.

The reward planner now carries the frozen role names, trajectories,
acquisition/reversal state, 8:3:1 exposure counts, and exact per-eligible-role
90/10 scheduling for ten-block software plans.

## 4. Intentional divergences and unresolved parity

The unified natural-image planner accepts the shared image suffix set and
keeps a generic transform policy; the frozen reward runner's persistent global
panel file and assignment-directory locking are not yet the production
storage integration. Local dual-camera capture intentionally replaces legacy
remote-camera transfer. Reward delivery, suction, lick, TTL, photodiode, and
real display timing remain hardware gates. These are documented in
`docs/source_parity_matrix.md` rather than treated as validated parity.

## 5. Asset-manifest implementation

`AssetManifest` records source stat identity, SHA-256, dimensions, mode,
selected occurrence counts, transform/background policy, target dimensions,
duplicate-content groups, and prepared-memory estimate. Preflight resolves and
hashes selected sources once. `AssetPreparer` verifies the source fingerprint
before and after decode and reuses immutable prepared bytes on cache hits.

## 6. Asset stress counts

The 5,000-frame synthetic campaign consumed 4,998 logical frames from a
bounded capacity-8 transport. It performed 7 source reads, 7 SHA-256
calculations, 7 decodes, and 7 renderer payload allocations. Peak transport
occupancy was 8 and underruns were 0.

## 7. Frame transport and prefetch

`BoundedFrameTransport` now has explicit finish and abort semantics with
blocked producer/consumer wakeups. `PrefetchCoordinator` runs one daemon
producer, uses low/high watermarks, exposes produced/consumed/peak/underrun
metrics, and reaps the producer on stop. The separate display-sequence adapter
uses immutable metadata, bounded ready-plus-inflight slots, contiguous producer
sequences, and idempotent acknowledgement.

## 8. Concurrency and abort tests

Threaded transport tests cover blocked put wakeup, blocked get wakeup, ordered
prefetch, EOF drain, fail-fast abort, and producer shutdown. The randomized
state-machine run exercised 1,000 seeds and 1,000 sessions with explicit
terminal outcomes.

## 9. Camera identity resolver

Fixture-driven `CameraIdentity`, `EnumeratedCamera`, `ResolvedCamera`, and
`CameraResolutionReport` types now resolve configured stable identities to
runtime selectors. Missing, duplicate, and family-mismatch cases fail closed.
Runtime selector, topology, family, and stable identity are recorded in the
camera manifest. `/dev/videoN` is never used as configured identity.

## 10. Subprocess camera torture results

Real local subprocess tests passed for normal continuous growth, immediate
nonzero failure, startup no-growth deadline, growth-then-stall, and a process
that ignores terminate and requires force-kill. The supervisor preserves
failure state, captures bounded stderr, records growth timestamps, and verifies
nonempty output separately from process exit. No subprocess was left running.

## 11. Storage safety results

Storage preflight rejects `/`, home-directory descendants, temporary-directory
fallbacks, and unsafe implicit recording roots. Optional bounded
write/fsync/delete probing is covered. A storage session creates a unique
directory and `.session-incomplete` marker, monitors free space, fsyncs files at
finalization, retains the marker on missing outputs, and removes it only after
successful finalization.

## 12. Session crash consistency

Session manifests begin incomplete, are atomically updated, and carry explicit
schema/data-format versions. Display results are streamed to JSONL with a
bounded summary. `inspect-session` reports state, last event, missing required
files, camera outcomes, and incomplete status without mutation. Cleanup errors
prevent a later `COMPLETE` status.

## 13. Orchestration and fault injection

The simulation runtime composes injected display, hardware, camera, telemetry,
storage/session, plan, lifecycle, and finalization boundaries. The deterministic
fault matrix covers session metadata, storage low-space, asset-manifest,
producer start/mid-session, display consumer start/mid-session, finalization,
and cleanup failures. Required/optional camera startup/crash/stall behavior is
covered by the camera supervisor tests.

## 14. 100-session campaign

The varied campaign ran 100 sessions, 20 for each of natural images, reward
conditioning, spout training, drifting gratings, and retinotopy. It varied
seeds, local-camera presence, optional-camera failure, required-camera failure,
and interruption points. Results: 89 `COMPLETE`, 9 expected `INTERRUPTED`, and
2 expected required-camera `FAILED`. Reported leaked threads/processes: 0.

## 15. Natural-image and reward golden coverage

Natural-image golden coverage passes against the committed deterministic
fixture. Reward plans produce 500 events, 220 eligible presentations, and 198
scheduled rewards, with exact 90/10 counts for each eligible role. No reward
hardware was actuated.

## 16. Telemetry stress

10,000 messages were published to a 256-entry in-memory sink. 256 were
retained and 9,744 were dropped by the bounded policy. The sink did not grow
without bound and no network telemetry was opened.

## 17. Data format and provenance

Session manifests now use schema version 2 and `phase4-v1` data-format
metadata. Provenance carries schema/data-format versions, source commit,
Python, platform, and machine. Display results use streaming JSONL plus a
bounded summary; camera, asset, storage, resource, and final-status artifacts
retain explicit structured metadata.

## 18. Mac profiling

The 100-iteration profile built 2,200 natural-image events in 0.229 seconds of
profiled time, with 102,469 calls and 71,106 peak traced bytes. The dominant
paths were plan construction, natural-image ordering, frame-offset creation,
dataclass replacement, and stable JSON serialization. This is not Pi timing
acceptance.

## 19. Static production-readiness audit

The static audit found no new unbounded queue, process-global random use, SSH
call, or frozen-reference write in the Phase 4 changes. Remaining placeholders
are intentional hardware/release boundaries or best-effort cleanup paths and
are listed in `docs/phase4_static_audit.md`.

## 20. Native sequence transport status

`docs/native_sequence_transport_abi.md` specifies bounded ready/in-flight
ownership, contiguous producer sequences, immutable payload metadata, timeout,
abort, and idempotent acknowledgement invariants. The portable native frame
self-test compiled and ran with `-Wall -Wextra -Wpedantic -Werror`. The full
Wayland/libdrm-linked native path remains unavailable on this Mac.

## 21. Fast test count

Final fast validation: `195 passed in 1.50s` from `python -m pytest -q`.
`python -m compileall -q src tests scripts`, `bash -n scripts/*.sh`,
`git diff --check`, and all 9 TOML example parses passed.

## 22. Stress and campaign counts

The separate heavy checks were: 5,000 logical asset frames; 1,000 randomized
state-machine sessions; 100 varied full dry-run sessions; 10,000 telemetry
messages; 100 reproducibility iterations; 100 profile iterations; five
subprocess camera modes; and the nine-fault runtime matrix.

## 23. Ruff, packaging, and native limitations

Ruff was not installed, so Ruff validation is unavailable rather than claimed.
The clean local package smoke was blocked because this Mac provides Python
3.12.4 while the project metadata requires Python >=3.13,<3.14. The portable
frame self-test passed with warnings-as-errors; the Wayland-linked lease
self-test could not link because the Mac environment lacks the required
Wayland library. No network dependency installation was attempted.

## 24. Hardware-gated items

No Pi SSH, camera, SSD, DRM acquisition, GPIO, reward valve, suction, lick
input, or photodiode access was attempted. Deferred gates are: HDMI-A-2 /
connector 42 visual-stimulus ownership; HDMI-A-1 / connector 33 camera-monitor
behavior; real camera topology and negotiated selectors; sustained camera
growth; SSD identity and throughput; combined display/camera/SSD resource
load; physical photodiode timing; and GPIO/reward safety. Existing real-hardware
measurements and raw traces were preserved unchanged.

## 25. Exact recommended next Pi commands

Run these only on the Pi after the experiment SSD is physically connected and
its identity is recorded; do not substitute the SD card or `/`:

```text
rpi-vstim preflight --config /path/to/production.toml --json
rpi-vstim hardware display-probe --config /path/to/production.toml --json
rpi-vstim hardware kms-probe --config /path/to/production.toml --lease --json
rpi-vstim hardware kms-render-smoke --config /path/to/production.toml --frames 300 --lease --json
rpi-vstim inspect-session /mnt/experiment-ssd/<session-id> --json
```

Then, using only the runtime selectors from the saved camera-resolution
report, run the two local camera workers into a disposable SSD acceptance
directory, repeat camera-off and combined display + dual-camera + SSD runs,
and save raw traces, resource logs, output-growth records, cleanup status, the
config digest, and this branch's commit. Keep HDMI-A-2 / connector 42 as the
visual target and HDMI-A-1 / connector 33 as the camera monitor. Do not enable
GPIO/reward or photodiode acceptance until the hardware owner confirms the
pin/polarity and sensor setup.

## Handoff

Production-like software boundaries are now in place for bounded assets,
display transport, local camera supervision, storage/session finalization,
telemetry, deterministic protocol planning, and hardware-free orchestration.
The remaining work is simulated or explicitly hardware-gated. The branch is
`codex/phase4-deep-integration` at the pushed report commit (parent
`d15b4cc`), with no merge to `main` and no Phase 01 work started.
