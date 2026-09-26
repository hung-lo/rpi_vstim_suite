# Camera workflow

The production design records two cameras locally on the same Raspberry Pi 5
that presents stimuli and controls behavior hardware. Each camera is selected
by a logical ID/role and stable device identity; `/dev/videoN` numbering alone
is not a production identity.

Phase 00 provides the configuration schema. The overnight software boundary
adds `LocalCameraSupervisor`: one independently supervised local process per
camera, deterministic `camera/<id>/capture.<extension>` outputs, bounded
status flow, startup/output-growth deadlines, clean stop with terminate/kill
fallback, required/optional policy, crash detection, and per-camera manifests.
The metadata-only fake service remains available for simulation. No SSH camera
control, cross-Pi transfer, or physical device access occurs.

Capture command construction is isolated and can target the audited `rpicam-*`
stack after stable identity resolution. The supervisor does not guess
`/dev/videoN`, and tests use fake processes only. Real capture, negotiated
modes, output growth, and timing acceptance remain hardware validation.

## Later hardware gate

The Phase 3 combined run is a short readiness baseline only. Before production
camera integration, resolve both IMX708 identities from stable topology data,
define an explicit measured stop deadline, verify per-camera output growth on
the experiment SSD, and compare camera-off versus dual-camera display timing
under the eventual capture mode. Camera workers must remain separate from the
display and GPIO timing paths; cleanup must leave no camera process behind.
