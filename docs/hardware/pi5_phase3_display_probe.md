# Scoped Phase 3 display-only work

Status: software implementation with discovery and scoped hardware validation.
Production storage is deferred until the experiment SSD is attached. No final
integrated display/GPIO/camera acceptance is claimed.

## Roles

The current physically verified roles are configurable as:

```text
HDMI-A-2 = stimulus display, connector 42
HDMI-A-1 = camera-preview display, connector 33
```

The final stimulus screen may change later; the rig profile must be updated and
revalidated if it does.

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
  CRTC restoration. Real leased page-flip runs, including the corrected
  HDMI-A-2 run, are recorded in the dated hardware reports.
- Unit fixtures cover dual connected HDMI outputs, disabled preview,
  disconnected/missing outputs, unsupported modes, exact/nearest refresh,
  reordered connectors, and role separation.

## Hardware work still blocked or deferred

The native code compiled and its read-only resource path passed on both real
outputs. Later supervised DRM-lease runs validated leased page flips and
recovery, including the combined display/two-camera trace. Physical photodiode
timing, SSD-backed storage, final-screen optical acceptance, GPIO, reward, and
production camera-supervisor acceptance remain deferred hardware validation.
