# Cameras

Configure each camera with stable topology identity, expected family, role,
and required status. `enumerate_rpicam_cameras()` reads
`rpicam-hello --list-cameras`. The supervisor resolves identities before
using transient numeric selectors. Two local CSI cameras can record MP4
directly into the session; preview is optional and needs a usable desktop.

Shutdown requests stop for every camera, then waits, verifies, and records
statuses. Production fast QC uses bounded MP4 metadata/probes; it does not
decode every frame. For slower offline counting:

```bash
rpi-vstim inspect-session /path/to/session --deep-camera-qc --json
```

See [camera workflow](camera_workflow.md) for the state model and
[dual_camera_recording.py](../examples/dual_camera_recording.py) for a short
explicit recording.
