# Pi 5 Phase 3 KMS/DRM bring-up — 2026-09-25

Starting commit: `f298987 Add SSD-independent Pi 5 display groundwork`

This report covers the SSD-independent display-only Phase 3 work. The
experiment SSD remains intentionally absent. No storage, boot, GPIO, reward,
camera, reference-repository, or `rpi_rig_monitor` changes were made.

## Software implementation

The repository now contains:

- a standalone direct-libdrm probe in `native/kms_display/kms_probe.c`;
- dynamic `/dev/dri/card*` discovery when no device is supplied;
- explicit connector, mode, refresh-tolerance, pixel-format, and photodiode
  patch options;
- read-only native `--probe-only` mode;
- two dumb buffers, deterministic alternating test patterns, synchronous
  page-flip events, monotonic/realtime callback timestamps, interval summary
  statistics, bounded event storage, signal handling, and CRTC restoration;
- a bounded Python subprocess wrapper and `KmsDisplayBackend`;
- Python timing summaries for median, p95, p99, min/max, estimated refresh,
  and out-of-tolerance intervals; and
- configurable photodiode patch bounds/value helpers.

The existing `FrameProgram` bridge intentionally maps to the native
test-pattern path. Production memory-mapped frame-cache loading and protocol
rendering are not claimed.

## Pi build and read-only native probe

Package metadata was inspected before installing the only missing build
dependency:

```text
libdrm-dev 2.4.134-3~bpo13+1+rpt1
```

Its required dependencies `libdrm-freedreno1`, `libdrm-intel1`, and
`libpciaccess-dev` were installed. GCC 14.2, make 4.4.1, and pkg-config 1.8.1
were already present. The source was built only in:

```text
/tmp/rpi-vstim-kms-phase3
```

The repository code was not installed or deployed to a persistent Pi path.

Native read-only probe results:

| Connector | DRM device | CRTC | Primary plane | Selected mode | RGB565 |
|---|---|---:|---:|---|---|
| HDMI-A-1 | `/dev/dri/card1` | 92 | 81 | `1024x600@59.8214` | `RG16` supported |
| HDMI-A-2 | `/dev/dri/card1` | 104 | 93 | `1024x600@59.8214` | `RG16` supported |

The probe performed no modeset or page flip. The HDMI-A-2 preview output was
not taken over.

## Modeset/page-flip smoke result

A 60-frame HDMI-A-1 test was attempted with:

```text
--device /dev/dri/card1
--connector HDMI-A-1
--width 1024 --height 600 --refresh 59.82
--format RGB565 --frames 60
```

Mode selection succeeded using the modeline-derived refresh
`59.8214286 Hz`. The first `drmModeSetCrtc` failed with:

```text
Permission denied
```

The active `labwc` process owns `/dev/dri/card1` on `seat0`, along with
`kanshi` and desktop-shell processes. The failure occurred before a modeset;
the probe reported `restored=false` and completed zero page flips. No process
was stopped and no session/boot configuration was changed.

Consequently there are no real-Pi page-flip intervals, missed-vblank counts,
or restoration-pass result to claim. The software path records those fields
when DRM ownership is available.

## Status classification

- **Verified real hardware:** Pi DRM card/connector/CRTC/primary-plane
  discovery, selected mode, RGB565 primary-plane support, and active labwc
  ownership.
- **Software-only validated:** native buffer/page-flip/restore implementation
  by compilation, Python wrapper, timing analysis, failure handling, and unit
  tests.
- **Provisional user-authorized assumption:** HDMI-A-1 is stimulus and
  HDMI-A-2 is camera preview; roles remain configurable.
- **Deferred:** physical page-flip timing, image/geometry validation,
  photodiode onset/polarity measurement, 10,000-frame acceptance, storage
  throughput, dual-camera load, and integrated GPIO/display/camera testing.

Canonical Gate 2 remains incomplete because production storage is deferred.
Canonical Gate 3 is not passed because modeset/page-flip acceptance could not
run while the compositor owned DRM master.
