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
- The standalone native probe and Python KMS wrapper provide bounded
  alternating-pattern/color page-flip presentation with timing fields and
  CRTC restoration.
- Unit fixtures cover dual connected HDMI outputs, disabled preview,
  disconnected/missing outputs, unsupported modes, exact/nearest refresh,
  reordered connectors, and role separation.

## Hardware work still blocked or deferred

The native code compiled and its read-only resource path passed on both real
outputs. A modeset/page-flip smoke test could not start because `labwc` owns
DRM master on `/dev/dri/card1`; no compositor changes were made. Real
page-flip intervals, physical photodiode timing, CRTC restoration under
ownership, and 10,000-frame acceptance remain unverified. No long stimulus,
reward/water/suction hardware, GPIO, dual-camera load, or integrated acceptance
test belongs in this scoped work.
