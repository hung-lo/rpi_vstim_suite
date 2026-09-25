# Display backend

The display contract is backend-neutral. `FakeDisplayBackend` remains the
backend used by software simulation. The Phase 3 slice adds a native
libdrm-backed `KmsDisplayBackend` for bounded alternating-pattern/color
presentation, with explicit timing results and fail-closed connector/mode
selection.

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

The native resource probe is:

```bash
rpi-vstim hardware kms-probe \
  --binary native/kms_display/kms_probe \
  --config config/rigs/pi5_dual_display_provisional.example.toml --json
```

It scans DRM cards when `--device` is omitted, resolves only the configured
stimulus connector, and performs no modeset or page flip. The short modesetting
smoke path is explicit:

```bash
rpi-vstim hardware kms-smoke --frames 60 --json
```

It allocates two bounded dumb buffers, uses synchronous page-flip events, and
restores the saved CRTC state. It must not be run while a compositor owns the
DRM master; diagnose that ownership first.

## Timing boundary

The native layer owns dumb-buffer allocation, synchronous page-flip events,
vblank sequence/timestamps, photodiode-patch writes, abort handling, and
restoration of the original CRTC state. The current `FrameProgram` bridge
intentionally presents deterministic native test patterns; frame-cache loading
and protocol rendering remain later work.

Python timing helpers report median, p95, p99, min/max, estimated refresh, and
intervals outside tolerance. Software timestamps are not physical photodiode
onsets. No full display timing acceptance or 10,000-frame stress result is
claimed.
