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

## Later hardware gate

The Phase 3 combined run is a short readiness baseline only. Before production
camera integration, resolve both IMX708 identities from stable topology data,
define an explicit measured stop deadline, verify per-camera output growth on
the experiment SSD, and compare camera-off versus dual-camera display timing
under the eventual capture mode. Camera workers must remain separate from the
display and GPIO timing paths; cleanup must leave no camera process behind.
