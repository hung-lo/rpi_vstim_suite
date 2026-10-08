# NVMe production session storage

The Pi 5 production SSD is a 953.9 GiB nominal NVMe device. Its existing ext4
filesystem UUID is `18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99`, mounted by the
existing fstab entry at `/mnt/behavbox_ssd`. A direct 1 GiB write measured
about 438 MB/s.

Production natural-image sessions use `/mnt/behavbox_ssd/sessions/<session-id>`
directly. There is no SD-card staging or post-session copy. Before any KMS,
camera, or GPIO acquisition, the runner requires a writable mount with source
`/dev/nvme0n1p1`, type `ext4`, the UUID above, and at least 20 GiB free. Failure
aborts rather than redirecting to a local path.

The session metadata records output-root, mount identity, capacity, and free
space at start and end. The intended operator command is:

```text
cd /home/pi/rpi_vstim_suite
rpi-vstim natural-images run --mouse-id V1_2 \
  --output-root /mnt/behavbox_ssd/sessions \
  --licks --cameras --camera-preview
```

PoE is not part of NVMe validation and remains pending hardware investigation.

## Validation results

The short full-stack session `V1_2_20261008T131729Z` completed on the NVMe
mount. Both camera files decoded: 1,062 frames at 30.0134 fps and 1,081 frames
at 30.0134 fps; both exited 0. HDMI-A-2 KMS requested and completed its frames,
HDMI-A-1 previews were active, and the JSONL event writer recorded 81 events
with zero drops and errors. The session provenance records source commit
`9179efeaff316fcfce5408512e3e38462adcafbb` and the expected NVMe identity.

The full-stack soak `V1_2_SSDsoak_20261008T132000Z` ran for about 30 minutes:
107,492 KMS frames requested/completed, 3,981 event records with zero drops or
errors, and both cameras exited 0. The two MP4s are 109,796,108 and
134,830,168 bytes; direct full decode probes report 54,003 frames in 1799.30 s
(30.014 fps) and 54,434 frames in 1813.66 s (30.013 fps), respectively. The
session occupied 250,383,012 bytes. NVMe free space
changed from 955,744,399,360 to 955,493,949,440 bytes; peak sampled temperature
was 54.9°C and `vcgencmd get_throttled` remained `0x0`. No NVMe I/O errors were
found in the kernel log.

After a clean reboot, `findmnt` again reported `/dev/nvme0n1p1` mounted rw at
`/mnt/behavbox_ssd`, and a one-image session smoke test completed on the NVMe.

## Coordinated camera-stop validation

Commit `f1dd3d7` was validated by the full-stack session
`V1_2_camera_stop_20261008T140000Z`. Both camera stop/reap timestamps were
recorded within 75.8 µs of one another, after 254.481 s of KMS acquisition;
the previous 15-second sequential-finalization skew is gone. The noir MP4 had
7,608 frames in 253.487109 s (30.01336 fps) and the wide MP4 had 7,579 frames
in 252.520815 s (30.01337 fps); both exited 0 and decoded cleanly. Their
0.966294 s duration difference is consistent with their 1.152 s serial startup
offset, and both cover the full display interval.

KMS requested and completed 15,026 flips, retained all 15,026 flip records,
restored cleanly, and reported two estimated extended refreshes, zero missed
vblanks, and non-contiguous kernel sequence. Each retained record has the true
kernel CLOCK_MONOTONIC vblank timestamp; session UTC is reconstructed from the
`CLOCK_SYNC` mapping, rather than from callback-receipt time. Event logging had
zero drops/errors, NVMe remained rw with no I/O errors, and throttling was
`0x0`.
