# Deployment

Deployment and bootstrap scripts are placeholders. The only target hardware
interaction performed for Phase 00 was the strictly read-only SSH inventory
recorded in `docs/hardware/pi5_initial_audit.txt`. The expanded reusable audit
script now includes local camera discovery, DRM connector/mode inventory,
media topology, and display/session information. It was not rerun from this
Mac; that verification is deferred until the lab network is reachable.

The production experiment target is one Pi 5 with two local cameras. SSH is a
deployment/audit transport only, not a camera-control or video-transfer path.
