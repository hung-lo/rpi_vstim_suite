# Display backend

The display contract is backend-neutral. `FakeDisplayBackend` remains the only
backend that presents frames in the software simulation. The scoped Phase 3
work adds a read-only DRM discovery path and a fail-closed `KmsDisplayBackend`
open/validation boundary; native page-flip presentation is not enabled yet.

## Configurable display roles

The `[display]` section has independent `stimulus_connector` and
`preview_connector` values. An empty preview value disables preview routing.
The provisional, user-authorized rig mapping is:

```text
stimulus: HDMI-A-1
preview:  HDMI-A-2
```

This is a configuration assumption, not a physical re-verification. Connector
names are not embedded in protocol code and can be swapped in a rig profile.

Mode selection requires the configured width/height and accepts a refresh only
within `refresh_tolerance_hz`. `require_exact_refresh` keeps the selection
fail-closed for the requested timing; no alternate connector is selected when
the configured one is missing, disconnected, or lacks the requested mode.

The read-only CLI path is:

```bash
rpi-vstim hardware display-probe --config config/rigs/pi5_dual_display_provisional.example.toml --json
```

It invokes `modetest -M vc4 -c`, parses connector status/modes, and reports the
selected stimulus and preview roles. It does not set a mode, take DRM master,
blank a display, or present a frame.

## Timing boundary

The eventual native backend must own dumb/GBM buffer allocation, synchronous
page-flip events, vblank sequence/timestamps, photodiode-patch writes, abort
handling, and restoration of the original CRTC state. The current Python KMS
boundary deliberately raises on `present()` until that native page-flip layer
is separately implemented and hardware-tested.

No display timing acceptance, photodiode timing acceptance, or 10,000-frame
stress result is claimed.
