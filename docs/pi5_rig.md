# Current Pi 5 deployment

This is the current Pi 5 rig, not the older Box151 2-photon rig.

The validated real runner uses
`config/rigs/pi5_natural_image_demo.example.toml`: leased KMS on HDMI-A-2,
optional preview on HDMI-A-1, two topology-identified CSI cameras, BCM26/27
lick inputs, and direct NVMe output. The checkout contains the 2,800-image
corpus at `assets/natural_images/stringer_natimg2800_center_crop/`. The real
command is:

```bash
rpi-vstim natural-images run --mouse-id <id> --config config/rigs/pi5_natural_image_demo.example.toml --licks --cameras --camera-preview
```

The corpus is present in this checkout at the path above. Its source,
verified transformations, CC BY-NC 4.0 license, and citation requirements are
documented in the [asset README](../assets/natural_images/stringer_natimg2800_center_crop/README.md).
The production storage guard checks this rig's NVMe and aborts on mismatch.
Reward, vacuum, and airpuff stay disabled in this demo.

BCM GPIO23 and GPIO24 are unassigned on this rig. There is no GPIO23 operator
bait button. Audio uses a C-Media Electronics / Unitek Y-247A USB adapter,
3.5 mm analog output, and a speaker. The repository now includes an optional
persistent `sounddevice`/PortAudio playback backend and an audio-only pilot;
audio uses no GPIO pins.

## USB audio characterization and coexistence

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
approximately 16.7 ms display frame at 60 Hz. The separate six-trial
audio-only pilot smoke completed as session
`audio-pilot-20261016T141736972643Z` with status `COMPLETE`: six requests, six
callback starts, zero missed requests, and zero callback status errors. These
software counters do not establish that every sound was acoustically heard.
Absolute command-to-acoustic latency has not been measured.

Full-stack coexistence was subsequently validated in the approximately
two-minute session
`av-coexistence-replay3-20261016211709Z`: natural-image KMS, both cameras,
event logging, NVMe, NeuroKairos IRIG-H, and persistent USB audio ran together.
All eight requests received callbacks, both cameras passed fast QC, KMS retained
all 7,217 frame records, and event drops/writer errors were zero. The
[validation record](hardware/pi5_av_coexistence_2026-10-16.md) contains full
measurements and scope. This is a short integration result, not audio endurance
or acoustic calibration. The phone-video observation confirmed audible output
qualitatively but did not measure acoustic onset or synchronization.
ALSA card numbering may change between boots. The configured device-name match
fails if zero or multiple playback devices match.

The [three-second pilot stimulus set](../assets/audio/pilot/README.md) provides
reproducible engineering WAVs. Its duration matches the current Go/NoGo sound
presentation duration; equal digital RMS does not imply equal perceived
loudness, and animal-facing SPL calibration remains required.

NeuroKairos is an [external service](https://github.com/SjulsonLab/neurokairos),
optional to VStim. Its sender can provide IRIG-H through BCM GPIO9; chrony is
a separate optional system-clock synchronization service. VStim neither
starts/stops the sender nor acquires GPIO9. Offline UTC/IRIG alignment is
possible when the signal is physically recorded.

The [hardware records](hardware/) document display, camera, NVMe, lick,
events, timing, thermal/power, and restoration validation. Final spout,
water calibration, mechanical fluidics, and animal testing are separate
apparatus work, not v0.1 core release gates.
