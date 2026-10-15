# Current Pi 5 deployment

The validated real runner uses
`config/rigs/pi5_natural_image_demo.example.toml`: leased KMS on HDMI-A-2,
optional preview on HDMI-A-1, two topology-identified CSI cameras, BCM26/27
licks, and direct NVMe output. The real command is:

```bash
rpi-vstim natural-images run --mouse-id <id> --config config/rigs/pi5_natural_image_demo.example.toml --licks --cameras --camera-preview
```

It requires a user-supplied natural-image corpus. The 2,800-image dataset
used in validation is not redistributed or assigned a license here. The
production storage guard checks this rig's NVMe and aborts on mismatch.
Reward, vacuum, and airpuff stay disabled in this demo.

BCM GPIO23 and GPIO24 are unassigned on this rig. There is no GPIO23 operator
bait button. Audio currently uses a Pi 5 USB audio adapter, its 3.5 mm analog
output, and a speaker. No VStim audio backend is installed or enabled.

## Provisional USB audio characterization

The detected adapter is a C-Media Electronics Inc. USB Audio Device, Unitek
Y-247A, seen as ALSA card 2, device 0 (`hw:2,0`) during this test. Playback
at 48 kHz through the speaker worked. A standalone persistent/preloaded
playback test requested 180 sounds, received 180 audio callbacks, and missed
zero requests.

| Standalone measurement | Median | Mean | SD | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Python trigger interval (ms) | 1000.000 | 1000.000 | 0.006 | 999.971 | 1000.046 |
| Trigger to audio callback (ms) | 2.654 | 2.696 | 1.572 | 0.068 | 5.957 |

A phone recording of the speaker showed stable acoustic onset at the few-ms
level with no missing beeps. This standalone variability was below one
approximately 16.7 ms display frame at 60 Hz. Absolute command-to-acoustic
latency has not been measured. This is provisional hardware characterization,
not full-stack validation; VStim with KMS, cameras, logging, and NeuroKairos
coexistence remains to be tested. ALSA card numbering may change between
boots. Audio implementation is a separate follow-up.

NeuroKairos is an [external service](https://github.com/SjulsonLab/neurokairos),
optional to VStim. It and chrony may continuously send IRIG-H through BCM
GPIO9. VStim neither starts/stops that sender nor acquires GPIO9. Offline
UTC/IRIG alignment is possible when the signal is physically recorded.

The [hardware records](hardware/) document display, camera, NVMe, lick,
events, timing, thermal/power, and restoration validation. Final spout,
water calibration, mechanical fluidics, and animal testing are separate
apparatus work, not v0.1 core release gates.
