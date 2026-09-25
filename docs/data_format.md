# Session data format

Phase 00 and simulation write `session_manifest.json`,
`resolved_config.json`, `provenance.json`, `events.csv`, and `plan.json` when a
session output is created. The manifest includes the protocol seed and source
commit used for reproducibility. Sessions with configured fake cameras also
write a bounded `camera_manifest.json`.

Simulation plans include stable event IDs, frame offsets, phase, trial and
sequence IDs, photodiode intent, and protocol metadata. Hardware event, lick,
camera media, and QC files remain reserved for later phases. Camera outputs
will be local per-camera session artifacts; they must not depend on a second
camera Pi or SSH transfer and must retain the legacy names documented in the
implementation plan where compatibility requires it.

Reward plans distinguish `reward_scheduled` from `reward_delivered`; planned
events use `null` for the latter until a runtime observation exists.
