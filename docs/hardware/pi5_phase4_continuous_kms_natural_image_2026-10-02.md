# Phase 4 continuous KMS natural-image validation — 2026-10-02

Status: software fix implemented; repeat phone-video acceptance remains
pending. Do not mark physical natural-image visual acceptance complete until
the uploaded repeat video confirms that the sustained bright intermediate
state is absent.

## Root cause

The earlier real-image validator called `KmsDisplayBackend.present_color()` and
`present_rgb_pair()` once per gray/image epoch. Each call launched a separate
`kms_probe` process. The native helper acquired a Wayland DRM lease, modeset,
page-flipped that epoch, restored the saved CRTC, and released the lease. The
compositor/restored framebuffer could therefore become visible between normal
stimulus states. This matches the video-observed bright blue-gray state.

The isolated one-camera-frame old/new mixtures remain consistent with
phone-camera/display scan timing and are not treated as a renderer bug.

## Resolution

`KmsDisplayBackend.present_sequence()` now sends immutable frame states through
one native stream process. The native lifecycle is:

1. acquire the lease once;
2. modeset once;
3. page-flip gray and image states continuously through two bounded scanout
   buffers;
4. restore the original CRTC once; and
5. release the lease once.

The Python producer queue is bounded at 32 packed frames and frame preparation
remains producer-side. Native input validates contiguous logical frame indices,
producer sequence numbers, payload sizes, photodiode metadata/payload
agreement, kernel page-flip sequence continuity, missed frames, and timing
intervals. Failure and interruption use the same single cleanup path.

## Real Pi evidence

Target: Raspberry Pi 5 `raspberrypi`, HDMI-A-2 / connector 42,
`1024x600@59.8214`, RGB565.

The representative two-image smoke completed 150/150 frames with one lease,
one modeset, one restore, one release, contiguous frame and kernel sequences,
zero missed/dropped/doubled frames, and zero intervals outside tolerance.

The five-image acceptance sequence used:

```text
gray(30) -> 0000(30) -> gray(30) -> 0700(30) -> gray(30)
-> 1400(30) -> gray(30) -> 2100(30) -> gray(30) -> 2799(30) -> gray(30)
```

It completed 330/330 frames with one continuous ownership interval, one
modeset, one restore, one lease release, contiguous logical/kernel sequences,
zero missed/dropped/doubled frames, zero intervals outside tolerance, and
photodiode metadata valid. The run artifact was
`/home/pi/tmp_task_runs/continuous-kms-real-natural-20261002`.

## Human acceptance gate

The operator must record and upload a repeat phone video of the same short
sequence. Acceptance requires no sustained bright alternate gray, compositor
flash, blank/loading state, or stale image lasting multiple complete camera
frames. A single partial old/new camera frame may remain because of
rolling-shutter/display-scan timing.
