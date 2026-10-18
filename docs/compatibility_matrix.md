# Overnight compatibility matrix

This matrix records the low-risk software compatibility work completed on the
overnight branch. It does not claim hardware compatibility.

| Area | Preserved | Explicitly changed or deferred |
| --- | --- | --- |
| Natural images | deterministic selection, exact image/repeat counts, no adjacent repeats, plain/camera final-ITI profiles, image metadata | display rendering, asset decoding, and camera capture are deferred |
| Reward conditioning | permanent assignment file, separate phase-state file, acquisition/reversal selection, 8:3:1 blocks, 90% schedule, 198/22 production outcome counts | observed delivery remains `null` until hardware/runtime observation; GPIO, lick, suction, and water actuation are deferred |
| Spout training | 8–12 s seeded intervals, schedule anchoring, recent-20 criterion, fake observed reward and water cap | real bait/reward/lick workers and operator modes are deferred |
| Drifting gratings | source defaults, seeded order/jitter, screen-plane cycles/cm, bar/drift semantics, phase progression, photodiode intent | Render/cache/session are implemented; Pi physical and photodiode-onset validation remain pending; cycles/degree is not defined |
| Retinotopy | source directions, fixed/shuffled seeded cycles, adjacent-bar polarity and trajectory, movement-to-refresh mapping, geometry frame plan | Render/cache/session and 2P-oriented frame metadata are implemented; Pi physical, photodiode onset, and downstream 2P pipeline validation remain pending |
| Telemetry | flat outer schema 1, `state`/`trial_complete`, payload schema 3, sequence/session/protocol fields, camera/error/degraded fields, bounded local AF_UNIX-to-UDP publisher | production session wiring and monitor-Pi validation remain deferred; no monitor-Pi dependency is introduced |
| Cameras | two independent local logical devices, required/optional state, metadata-only manifests | no `/dev/video*` resolution, capture, SSH, remote camera, or cross-Pi transfer |

The four source repositories are read-only references. Source commits and
ownership are recorded in `docs/source_baseline.md` and `docs/migration_matrix.md`.
