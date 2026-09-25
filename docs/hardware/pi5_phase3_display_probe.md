# Scoped Phase 3 display-only work

Status: software-only and discovery-level hardware validation. Full Gate 2 is
incomplete because production storage is deferred until the experiment SSD is
attached. No final integrated display/GPIO/camera acceptance is claimed.

## Roles

The user-authorized provisional roles are configurable as:

```text
HDMI-A-1 = stimulus display
HDMI-A-2 = camera-preview display
```

These are provisional assumptions, not a new physical cable verification.

## Implemented

- `DisplayConfig` has separate stimulus and preview connector roles.
- `modetest -c` output is parsed without assuming DRM card or connector
  numbering.
- Mode selection requires the configured connector, connection status,
  dimensions, and refresh tolerance; it never falls back to another output.
- `rpi-vstim hardware display-probe` reports the selected roles without setting
  a mode or presenting frames.
- The Python KMS boundary can open/validate against the read-only probe but
  fails closed on presentation until native page-flip code exists.
- Unit fixtures cover dual connected HDMI outputs, disabled preview,
  disconnected/missing outputs, unsupported modes, and role separation.

## Deferred native/hardware work

The native boundary still needs a short, controlled implementation and test of
synchronous page flips, vblank sequence/timestamps, bounded presentation
buffers, photodiode-patch writes, abort handling, and restoration of the prior
CRTC state. No long stimulus, reward/water/suction hardware, GPIO, dual-camera
load, or 10,000-frame acceptance test belongs in this scoped work.
