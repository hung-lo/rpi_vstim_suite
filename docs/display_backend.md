# Display backend

The display contract is backend-neutral. `FakeDisplayBackend` remains the
backend used by software simulation. The native libdrm-backed
`KmsDisplayBackend` supports bounded single-epoch smoke calls and the
continuous `present_sequence()` path used for real protocols, with explicit
timing results and fail-closed connector/mode selection.

## Configurable display roles

The `[display]` section has independent `stimulus_connector` and
`preview_connector` values. An empty preview value disables preview routing.
The current physically verified Pi 5 rig mapping is:

```text
stimulus: HDMI-A-2
preview:  HDMI-A-1
```

The mapping was verified by a short HDMI-A-1-only leased pattern observed on
the camera monitor, followed by a short HDMI-A-2-only leased control. Connector
names are not embedded in protocol code and can be swapped in a rig profile.

Stimulus mode selection requires the configured width/height and accepts a
refresh only within `refresh_tolerance_hz`. `require_exact_refresh` keeps the
stimulus selection fail-closed for the requested timing. Preview discovery only
checks the configured connector's identity and connected status because labwc
owns its mode; it does not impose the stimulus resolution/refresh on the
camera-monitor output.

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
kernel event timestamps, callback-dispatch diagnostics, abort handling, and
restoration of the original CRTC state. A continuous stream acquires the lease
once, modesets once, consumes packed frame states through two scanout buffers,
and restores/releases once after EOF or interruption. No gray/image epoch
reacquires DRM ownership. `ProductionFrameRenderer` converts prepared RGB888
frames into bounded RGB565 or XRGB8888 payloads and applies the photodiode
patch before submission; the bounded Python producer queue never represents an
entire experiment in memory.

Python timing helpers report median, p95, p99, min/max, estimated refresh, and
intervals outside tolerance, long/short intervals, and estimated dropped
frames with an explicit timestamp source. Kernel event timestamps are preferred
for interval summaries; callback timestamps remain a separate dispatch
diagnostic. Compare dispatch latency only within one clock domain:
`kernel_timestamp_clock = monotonic` uses `callback_monotonic_ns`,
`realtime` uses `callback_realtime_ns`, and `unknown` does not support an
absolute latency value. Matching clock domains do not make the timestamp
instants equivalent: `kernel_event_ns` is a DRM vblank timestamp, while the
callback fields are userspace receipt timestamps. A signed callback-minus-
kernel delta can therefore be negative and remains a driver/timestamp
diagnostic until independently calibrated. Never subtract timestamps from
different clock domains. Neither is a physical photodiode onset. Native KMS
errors distinguish readable/enumerable resources from modesetting ownership;
when labwc owns the DRM master, the result is an ownership block rather than a
generic display failure. The corrected HDMI-A-2 10,000-frame run and the
real-Pi production-renderer smoke are documented in the hardware report.

The combined display/two-camera trace has a separate software-timestamp
analysis in `docs/hardware/pi5_phase3_timing_analysis_2026-09-25.md`; its
compensating long/short intervals are not optical acceptance.

On the current Pi, labwc 0.9.2 with wlroots 0.19 exposes
`wp_drm_lease_device_v1` and offers both HDMI outputs. The ownership and
physical-role validation are documented in
`docs/hardware/pi5_phase3_drm_lease_2026-09-25.md`.
