# Camera workflow

The production design records two cameras locally on the same Raspberry Pi 5
that presents stimuli and controls behavior hardware. Each camera is selected
by a logical ID/role and stable device identity; `/dev/videoN` numbering alone
is not a production identity.

Phase 00 provides the configuration schema. Overnight groundwork adds a
metadata-only fake service that exercises independent per-camera start/stop,
required/optional failure, degraded state, and session manifests. No SSH camera
control, cross-Pi transfer, recording, conversion, or device access occurs.
Future capture uses one independently supervised worker per camera, bounded
buffering, direct-to-session storage, and post-session verification.
