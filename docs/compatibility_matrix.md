# Overnight compatibility matrix

This matrix records the low-risk software compatibility work completed on the
overnight branch. It does not claim hardware compatibility.

| Area | Preserved | Explicitly changed or deferred |
| --- | --- | --- |
| Natural images | deterministic selection, exact image/repeat counts, no adjacent repeats, plain/camera final-ITI profiles, image metadata | display rendering, asset decoding, and camera capture are deferred |
| Reward conditioning | permanent assignment file, separate phase-state file, acquisition/reversal selection, 8:3:1 blocks, 90% schedule, 198/22 production outcome counts | observed delivery remains `null` until hardware/runtime observation; GPIO, lick, suction, and water actuation are deferred |
| Spout training | 8–12 s seeded intervals, schedule anchoring, recent-20 criterion, fake observed reward and water cap | real bait/reward/lick workers and operator modes are deferred |
| Drifting gratings | source defaults, seeded order/jitter, frame timing, drift direction, photodiode intent | pixel generation/cache and display calibration are deferred |
| Retinotopy | source directions, fixed/shuffled seeded cycles, movement/refresh frame conversion, sweep metadata | geometry rendering, display calibration, TTL, and 2P integration are deferred |
| Telemetry | flat outer schema 1, `state`/`trial_complete`, payload schema 3, sequence/session/protocol fields, camera/error/degraded fields | no UDP socket or monitor-Pi dependency is introduced |
| Cameras | two independent local logical devices, required/optional state, metadata-only manifests | no `/dev/video*` resolution, capture, SSH, remote camera, or cross-Pi transfer |

The four source repositories are read-only references. Source commits and
ownership are recorded in `docs/source_baseline.md` and `docs/migration_matrix.md`.
