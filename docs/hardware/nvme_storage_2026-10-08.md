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

## 90-minute event-queue-fix endurance retry

Commit `bd09b258f2eae117fb75cd7a5048ae8e7da3bbbe` passed the production-like
retry session `V1_2_90min_soak_retry_20261008T160000Z`. The display +
dual-camera + event logging + NVMe stack passed a 90-minute production-like
endurance validation after the event-queue overflow fix.

The session ran for 5,429.947 s of KMS acquisition on
`/mnt/behavbox_ssd/sessions/V1_2_90min_soak_retry_20261008T160000Z`.
The event queue remained bounded at 4,096 entries and reached a high-water
mark of 4,096, but the reliable shutdown handoff drained it completely:
12,021 enqueued, 12,021 written, zero dropped, and zero writer errors. The
session finalized `COMPLETE`; the failed earlier session
`V1_2_90min_soak_20261008T141500Z` remains preserved as evidence.

KMS requested/completed 324,774/324,774 presentations and retained
324,774/324,774 timing records with no truncation. It reported 54 estimated
extended refreshes, zero missed vblanks, and non-contiguous kernel sequence.
The first and last kernel presentation timestamps were
15,210,589,360,000 ns and 20,640,536,458,000 ns on CLOCK_MONOTONIC. The KMS
path remains droppable but timing-observable: scientific reconstruction must
use the retained kernel-vblank timestamps, with UTC derived through
`CLOCK_SYNC`, rather than nominal frame rate or callback receipt time.

Both cameras started before display acquisition, stopped together, and exited
0. Stop/reap skew was 134.13 µs. The noir and wide MP4s were 312,382,700 and
399,800,245 bytes with container durations 5,436.384854 s and 5,435.451186 s;
both therefore cover the complete 5,429.947 s scientific display interval and
include only ordinary lead-in/tail footage. The supervisor's bounded 15-second
full-frame probe reported `recorded_unverified` for these large files, so an
exact decoded-frame count was not attempted during shutdown; lightweight
container duration/size checks succeeded.

The session occupied 795,711,631 bytes. NVMe free space changed from
954,536,501,248 to 953,740,722,176 bytes. The mount remained
`/dev/nvme0n1p1`/ext4/rw with UUID
`18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99`; no new NVMe, PCIe, ext4, I/O, or
read-only-remount errors were found. Peak/final temperature was 45.5°C,
`vcgencmd get_throttled` remained `0x0`, and available memory remained about
1.5 GiB at final inspection. No recording `rpicam-vid` processes remained and
LabWC/KMS restoration was successful.

## Fast bounded MP4 QC validation

Commit `b864af2a67b032fd7d3fa0b1d724f021ba988fb0` introduced the verifier.
The full-stack short recording below was created on that commit. Follow-up
commit `b29e34542969d451d2a81f73578949f00a29a3ad` removed even the unused
`nb_read_frames` field from the fast probe request and is deployed to the
permanent Pi checkout. The normal-shutdown verifier uses metadata-only
`ffprobe` with a five-second timeout per camera and does not request
`-count_frames` or `nb_read_frames`. It checks file size (at least 1 KiB), MP4/container and video
stream readability, H.264 codec, requested dimensions and sensible frame
rate, stream time base, start time and positive duration. It also checks the
media duration against the camera process lifetime and, when available, checks
the ready/stop lifecycle and media duration against the first/last KMS
CLOCK_MONOTONIC presentation timestamps. A failed check marks a required
camera failed and prevents a healthy `COMPLETE` result.

The preserved 90-minute session above was inspected read-only with the new
`inspect-session` fast checks. Both historical camera manifest entries remain
unchanged as `recorded_unverified`; the new inspection independently reported
both files healthy and covering the KMS interval. Final metadata probes took
0.185 s per camera; complete final `inspect-session --json` took 1.475 s.
The files reported H.264 640x480, 30.0133/30.0131 metadata fps, and durations
of 5,436.384854 s / 5,435.451186 s. The original session artifacts were not
modified.

The short real full-stack validation session
`V1_2_mp4_fast_qc_short_20261008T205408Z` completed on the NVMe with status
`COMPLETE` after 414.233 s of KMS acquisition. Both in-shutdown verifiers
reported `recorded`, production QC success, and scientific interval coverage;
both camera processes exited 0. The saved short-session MP4s were then
re-inspected read-only with final commit `b29e345`; both fast checks passed.
The noir MP4 was 22,054,748 bytes,
416.647467 s, and 30.01338 metadata fps; the wide MP4 was 32,965,391 bytes,
415.714585 s, and 30.01338 metadata fps. No exhaustive frame count was run.

KMS requested/completed 24,777/24,777 flips and retained 24,777/24,777 timing
records without truncation. It reported four estimated extended refreshes,
zero missed vblanks, and non-contiguous kernel sequence; restoration succeeded.
Event logging wrote all 921 enqueued events with zero drops and errors and a
queue high-water mark of 900/4,096. The session occupied 61,497,715 bytes;
free space changed from 953,740,718,080 to 953,679,147,008 bytes. NVMe
remained ext4/rw. Temperature peaked at 52.1°C and was 45.0°C after shutdown;
`get_throttled` remained `0x0`. Available memory returned from about 1.2–1.3
GiB during recording to 1.5 GiB afterward. No camera recording processes
remained, and LabWC stayed alive after KMS restoration.

The final deployed commit `b29e34542969d451d2a81f73578949f00a29a3ad` then ran
`V1_2_mp4_fast_qc_final_20261008T210947Z` for an exact-revision shutdown check.
It completed 305.576 s of KMS acquisition with status `COMPLETE`. Both
camera processes exited 0 and their fast shutdown checks reported
`verification_state=recorded` and full KMS interval coverage. Noir was
16,871,048 bytes / 307.862773 s / 30.01337 metadata fps; wide was
25,130,009 bytes / 306.929917 s / 30.01337 metadata fps. KMS requested and
completed 18,280 flips, retained all 18,280 records without truncation,
reported one estimated extended refresh and zero missed vblanks, and restored
the display. All 681 enqueued events were written with zero drops/errors
(queue high-water 664/4,096). NVMe free space changed from 953,679,147,008 to
953,632,296,960 bytes; the session occupied 46,786,993 bytes. Temperature
peaked at 52.1°C and was 47.2°C after shutdown, `get_throttled` was `0x0`, and
available memory returned to 1.5 GiB. No camera process remained and LabWC
stayed alive.

For explicit offline exhaustive frame counting, run
`cd /home/pi/rpi_vstim_suite` followed by
`PYTHONPATH=src python3 -m rpi_vstim inspect-session <session-path> --deep-camera-qc --json`.
The production verifier does not prove that every encoded frame decodes cleanly,
contains no timestamp gaps, or has no duplicates; frame-level integrity
requires this optional offline QC.
