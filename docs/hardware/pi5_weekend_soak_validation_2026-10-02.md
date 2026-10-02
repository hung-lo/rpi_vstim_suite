# Pi 5 weekend remote reliability validation — 2026-10-02

## Scope and release under test

The production release candidate was based on commit `c5a166b` on
`codex/pre-hardware-rc-hardening`. Testing used the existing display renderer,
camera commands, session validators, and `LgpioLickMonitor` without changing
GPIO mappings, lick thresholds, GPIO15 behavior, or reward/vacuum behavior.

Only idle lick-input monitoring was used remotely. No physical lick contacts
were requested or injected, and no reward/vacuum output was accessed.

## Commands and software checks

Existing software campaigns completed:

| Command | Result |
|---|---|
| `python scripts/soak_virtual_sessions.py --sessions 20` | 20 COMPLETE; zero thread/FD/child-process deltas |
| `python scripts/leak_campaign.py --iterations 20` | 16 COMPLETE, 4 INTERRUPTED; zero thread/FD/child-process deltas |
| `python scripts/virtual_rig_campaign.py --sessions 20` | 20 COMPLETE; all inspected |
| `python scripts/crash_consistency_campaign.py` | 8 terminal-boundary cases; all inspection results stable |
| `pytest -q` | 237 passed |
| targeted lick tests | 9 passed; touched validator file lint-clean |

The built-in 1,000-session virtual soak was started but stopped because it
was disproportionately slow in this environment; it was not used as a pass
criterion.

The existing `FakeLgpio` injection path exercised raw edge → classifier →
`LickEventRecorder` for independent LEFT/RIGHT streams. Raw edges and
classified events remained distinct, with release and minimum-interval
behavior covered by the existing tests. This is software-path validation only.

## Repeated Pi lifecycle

The corrected integrated validator was run for 20 independent cycles. Each
cycle started and stopped both cameras, the leased display smoke, and idle
GPIO26/27 monitoring using a unique output directory.

- 20/20 cycles completed normally.
- 20/20 display runs completed 300/300 frames.
- 19/20 display runs reported contiguous frame and kernel sequences; one run
  had three estimated dropped frames in isolated ~33 ms intervals.
- 20/20 reported one lease acquire, one modeset, one restore, and one lease
  release.
- 20/20 restored the display.
- 20/20 ended with GPIO26/27 LOW and released.
- Raw/classified lick counts were both zero, as expected with no contacts.
- No stale camera, renderer, validator, or lick-monitor processes remained.

The first campaign exposed one validator race where the display process was
stopped at the exact duration boundary before its JSON finished. The harness
now waits for display completion before using termination as a fallback.

## Long combined idle soak

The KMS native probe caps one synchronous run at 10,000 frames, so the soak
used four sequential 9,000-frame chunks while both cameras and one continuous
idle GPIO26/27 monitor remained active. Total display time was approximately
10 minutes and total requested display frames were 36,000.

| Measure | Result |
|---|---:|
| Display chunks | 4 |
| Frames per chunk | 9,000/9,000 |
| Display frame/kernel continuity | True for all chunks |
| Estimated dropped/missed frames | 4 |
| Estimated doubled frames | 0 |
| Display restoration | True for all chunks |
| Per-chunk ownership lifecycle | 1 acquire / 1 modeset / 1 restore / 1 release |
| Maximum observed vblank interval | 33,433 µs |
| Camera 0 encoded packets | 18,198 |
| Camera 1 encoded packets | 18,192 |
| Camera stream decode | Clean for both streams |
| Final GPIO26/27 state | Inputs, LOW, released |

The four display gaps were isolated ~33.4 ms intervals: none in chunk 1,
one in chunk 2, three in chunk 3, and none in chunk 4. A display-only
comparison of two 9,000-frame chunks produced zero drops/doubles and contiguous
sequences, so the observed gaps correlate with concurrent camera load. This is
recorded as a reliability observation, not a pass for zero-drop long-run
operation.

Resource snapshots during the combined soak showed approximately 1.24–1.29 GB
available RAM, 45.8–49.1°C CPU temperature, and 34–35% root filesystem use.
The camera processes remained active during the soak and no child processes
remained after cleanup. Existing libcamera warnings about missing static
IMX708 sensor properties were present; no camera startup failure occurred.

## Safe interruption and recovery

A 30-second integrated session was interrupted remotely with SIGINT after
startup. The command exited through the SSH/PTY interruption path. Afterward:

- no camera, renderer, validator, or lick-monitor child process remained;
- GPIO26/27 were released inputs and LOW;
- the partial output directory was clearly incomplete (`display.json` empty,
  short partial camera files);
- a new 20-second integrated session started immediately afterward;
- both cameras exited 0, the display exited 0, and the display restored.

The validator also now requests SIGINT for normal camera shutdown, producing
cleanly decodable H.264 output instead of relying on SIGTERM at the duration
boundary.

## Bugs and fixes

Validation-only issues found and fixed:

1. The integrated validator could terminate the display subprocess at the
   exact duration boundary before its completed JSON was written. It now waits
   for normal display completion and only falls back to termination after a
   timeout.
2. The validator used SIGTERM for normal camera shutdown, which could leave a
   truncated final H.264 macroblock. It now uses SIGINT for camera cleanup.

No production GPIO mapping, polarity, classifier threshold, display renderer,
or physical wiring behavior was changed.

## Remaining physical validation

The remote tests intentionally do not claim physical lick integration.

> Run the integrated full-stack smoke with real physical LEFT and RIGHT lick
> contacts while display and both cameras are active, and verify classified
> events, raw events, zero cross-talk, and clean release.

The branch is suitable for that final in-person physical smoke, but the
observed four isolated display timing gaps under concurrent camera load should
remain an open reliability observation before claiming zero-drop long-run
acceptance.
