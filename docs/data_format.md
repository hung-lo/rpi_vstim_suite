# Session data format

Phase 00 writes `session_manifest.json`, `resolved_config.json`, and
`provenance.json` when a session output is explicitly created. The manifest
includes the protocol seed and source commit used for reproducibility.

Protocol event, plan, reward, lick, camera, and QC files are reserved for later
phases. Camera outputs will be local per-camera session artifacts; they must
not depend on a second camera Pi or SSH transfer and must retain the legacy
names documented in the implementation plan where compatibility requires it.
