# Pi 5 natural-image demo validation — 2026-10-06

Branch: `codex/pre-hardware-rc-hardening`  
Demo commit deployed: `79af73f`  
Pi: `pi@10.42.84.10`  
Stimulus: HDMI-A-2 / DRM connector 42  
Camera monitor: HDMI-A-1 / DRM connector 33

The deployed checkout is an archive without `.git`; the demo was run from the
source deployed from commit `79af73f`. The session’s existing provenance helper
therefore reported an unavailable local Git identity unless
`RPI_VSTIM_SOURCE_COMMIT=79af73f` is supplied explicitly on archive deployments.
This is a deployment limitation to fix before treating archive sessions as
production provenance.

## Implemented path

The runner used the real 2,800-image corpus and the existing
`natural_legacy_plain` / `crop` policy. It used one continuous leased KMS
sequence, native rpicam previews, the stable CSI identities, and only BCM26 /
BCM27 licks. Reward, vacuum, GPIO15, GPIO23, GPIO24, and GPIO9 were untouched.

Native preview commands were:

```text
rpicam-vid --camera 0 --no-raw --timeout 0 --output .../camera/imx708_noir/capture.h264 --preview 0,0,512,384 --width 640 --height 480 --framerate 30 --codec h264
rpicam-vid --camera 1 --no-raw --timeout 0 --output .../camera/imx708_wide_noir/capture.h264 --preview 512,0,512,384 --width 640 --height 480 --framerate 30 --codec h264
```

The Pi’s installed `rpicam-vid` help confirmed `--preview x,y,width,height`
and `--roi`; no custom crop/decoder path was added. ROI/FoV reduction remains
deferred.

## Timing comparison

| Case | Run | Frames | Timing source | Missed | Dropped | Doubled | Kernel contiguous | Restore/lifecycle |
|---|---|---:|---|---:|---:|---:|---|---|
| A: licks, no cameras | `A_79af73f` | 755 | kernel event | 0 | 0 | 0 | yes | 1/1/1/1 |
| B: licks + cameras, preview off | `B_79af73f` | 755 | kernel event | 0 | 0 | 0 | yes | 1/1/1/1 |
| C: licks + cameras, preview on | `V1_2_demo_79af73f` | 1,987 | kernel event | 0 | 0 | 0 | yes | 1/1/1/1 |

The lifecycle values are lease acquire / release / modeset / restore counts.
The C run reported one continuous display ownership interval and zero event
handoff drops/errors. Its display trace contained 1,987 retained flip events.

## Camera result

Both stable camera identities started and stopped cleanly in case C. The
recordings were:

- `imx708_noir`: 2,007,040 bytes;
- `imx708_wide_noir`: 2,707,456 bytes.

`ffprobe` identified both as H.264 640x480 streams, and `ffmpeg` decoded one
frame from each with exit code 0. No `rpicam-vid` or `kms_probe` process
remained after shutdown. The native previews were requested simultaneously at
the two non-overlapping HDMI-A-1 geometries; this report does not claim optical
window-placement acceptance without an operator visual check.

## Unified event/log result

Case C produced `events.jsonl` with UTC, derived UTC nanoseconds, source
monotonic nanoseconds, and session elapsed time on every record. It contained
`CLOCK_SYNC`, 20 `IMAGE_ONSET` records, 22 gray-onset records, raw/classified
lick stream types, camera lifecycle records, and display lifecycle records.
The display image/gray boundary records used DRM callback monotonic timestamps.
No per-camera-frame events were written.

## Lick result and remaining acceptance

The two attempted physical-demo sessions (`V1_2_demo_79af73f` and
`V1_2_licks_79af73f`) both recorded:

```text
raw lick_left=0, raw lick_right=0
classified lick_left=0, classified lick_right=0
```

Therefore the runner path was exercised with the real dual lick monitor, but
the required physical acceptance was **not** completed. Do not interpret the
zero counts as a passed 10-left/10-right test. A subsequent operator-present
run must produce exactly 10 physical LEFT and 10 physical RIGHT contacts,
with raw edges retained, exactly 10 classified events on each channel, zero
cross-talk, and clean release.
