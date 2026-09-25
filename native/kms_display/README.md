# KMS display native boundary

`kms_probe.c` is the standalone direct-libdrm Phase 3 probe. It dynamically
finds the card exposing the configured connector unless `--device` is supplied,
selects the requested mode, checks the primary plane format, allocates two
dumb buffers, performs synchronous page-flip events, records timing, and
restores the saved CRTC state.

`--probe-only` enumerates the selected device, connector, mode, CRTC, primary
plane, and supported formats without modesetting. The normal path is a short
alternating-pattern test with a configurable photodiode patch. It does not
involve cameras, GPIO, storage, or telemetry.

Build on Debian Trixie with:

```bash
make
```

The current repository wrapper exposes this as `KmsDisplayBackend`, but the
backend is not production protocol rendering: `FrameProgram` currently maps to
the bounded native test-pattern path. Full frame-cache integration, physical
photodiode validation, and 10,000-frame acceptance remain later gates.
