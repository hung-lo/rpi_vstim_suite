# Deployment and hardware boundaries

Production deployment remains deferred while the experiment SSD is absent.
The current Phase 2 audit is recorded in
`docs/hardware/pi5_phase2_audit_2026-09-25.md`; it preserves the observed
`/etc/fstab` reference to `/mnt/behavbox_ssd` and does not invent an `/mnt/hd`
mapping.

The permanent Pi deployment target is `/home/pi/rpi_vstim_suite`, cloned from
the `codex/pre-hardware-rc-hardening` branch. Keep
`/home/pi/rpi_vstim_suite-345d8ee` intact as the temporary rollback snapshot
until the Git checkout, natural-image asset digest, system-site-package venv,
and hardware smoke test have all passed. The 2026-10-07 migration attempt did
not create the checkout because Pi-to-GitHub SSH stopped at `Host key
verification failed`; no source snapshot, SSD, mount, or `/etc/fstab` state
was changed.

The package now provides a read-only display discovery command:

```bash
rpi-vstim hardware display-probe \
  --config config/rigs/pi5_dual_display_provisional.example.toml --json
```

The current physically verified roles are HDMI-A-2 for visual stimulus and
HDMI-A-1 for camera preview. The roles remain configuration, not protocol
constants, and can be swapped without code changes if the final screen or cable
layout changes. The command does not set modes or present frames. The explicit
native KMS smoke command performs short page-flip testing only when the caller
has confirmed DRM ownership and can restore the saved CRTC state.

The production experiment target is one Pi 5 with two local cameras. SSH is a
deployment/audit transport only, not a camera-control or video-transfer path.
