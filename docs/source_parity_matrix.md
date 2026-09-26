# Frozen-source behavioral parity matrix

References were inspected read-only at the audited commits recorded in
`docs/migration_matrix.md`. The local reference repositories were not changed.

| Behavior | Natural images | Natural-image reward conditioning | Classification |
|---|---|---|---|
| image discovery/filter/order | deterministic sorted paths; unified accepts the shared image suffix set | frozen reward source requires a validated 14-image panel | intentional suffix generalization; reward panel unresolved |
| selected subset/seed | 5 images, sorted `Random(777).sample` | persistent panel/assignment seeds and mouse identity | natural exact; reward contract not yet ported |
| repeat/order | seeded bucket shuffle with no adjacent repeats | frozen 8:3:1 role exposure and no adjacent repeats | natural exact; reward unresolved |
| pre/post gray | 180 frames at 60 Hz, gray 127, photodiode off | stimulus protocol controls are defined, runtime display is separate | natural exact; reward hardware-free plan partial |
| ITI/duration | inclusive integer 42–60 frames, seed `task_seed + 1`; image 30 frames | frozen reward source uses continuous 3.0–4.5 s planning | natural exact; reward unresolved |
| resize/background/color | centered LANCZOS crop, RGB conversion, gray 127 | source uses the same image panel but display path is separate | natural exact under compatibility profile; generic `fit_pad` remains intentional |
| photodiode | legacy policy recorded as top-right 120 px white/black patch | TTL/reward timing is not a display substitute | intent recorded; physical validation gated |
| reward/omission/reversal | not applicable | frozen source has role trajectories, exact 90/10 rewards/omissions, and explicit acquisition/reversal | unresolved unified reward parity |
| camera ordering/output | local dual-camera supervisor and session-local outputs | frozen source used remote camera transfer/cleanup | intentional architecture divergence |
| TTL/lick/reward events | TTL contract remains hardware-gated | reward delivery remains null until worker acknowledgement | hardware-gated |
| interruption/cleanup | transactional session work continues on this branch | frozen source has explicit camera-left-running and cleanup states | software boundary in progress |

The natural-image fixture tests use a small synthetic filename set and the
frozen seed values; they do not vendor reference source or image data. The
reward-conditioning rows are intentionally marked unresolved rather than
silently claiming parity.
