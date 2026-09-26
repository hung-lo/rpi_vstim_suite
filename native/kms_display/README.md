# KMS display native boundary

`kms_probe.c` is the standalone direct-libdrm Phase 3 probe. It dynamically
finds the card exposing the configured connector unless `--device` is supplied,
selects the requested mode, checks the primary plane format, allocates two
dumb buffers, performs synchronous page-flip events, records timing, and
restores the saved CRTC state.

`--probe-only` enumerates the selected device, connector, mode, CRTC, primary
plane, and supported formats without modesetting. The normal path is a short
alternating-pattern test with a configurable photodiode patch. `--frame-file`
accepts exactly two packed frames (logical frame 0/on followed by logical frame
1/off), allowing the bounded production renderer to feed the same native leased
KMS path. It is a bounded two-frame smoke/validation transport, not the
finished natural-image sequence transport. The Python wrapper currently uses a
short-lived temporary file for this diagnostic path; production protocol
rendering must not depend on it. It does not involve cameras, GPIO, storage,
or telemetry.

Build on Debian Trixie with:

```bash
make
```

The repository wrapper exposes this through `KmsDisplayBackend` and
`ProductionFrameRenderer`. Asset decoding remains caller-owned; the renderer
keeps only a bounded prepared-frame cache. Physical photodiode validation,
storage, and integrated acceptance remain later gates.
