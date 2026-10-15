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

BCM GPIO23 and GPIO24 connect to Robertsonics WAV Trigger external inputs 1
and 2. They are configured as `sound_trigger_1` and `sound_trigger_2`, but
VStim does not claim or pulse them yet. The sound associated with each input
depends on the WAV Trigger SD-card/configuration; neither is assigned a
protocol cue here. There is no GPIO23 operator bait button on this rig.

NeuroKairos is an [external service](https://github.com/SjulsonLab/neurokairos),
optional to VStim. It and chrony may continuously send IRIG-H through BCM
GPIO9. VStim neither starts/stops that sender nor acquires GPIO9. Offline
UTC/IRIG alignment is possible when the signal is physically recorded.

The [hardware records](hardware/) document display, camera, NVMe, lick,
events, timing, thermal/power, and restoration validation. Final spout,
water calibration, mechanical fluidics, and animal testing are separate
apparatus work, not v0.1 core release gates.
