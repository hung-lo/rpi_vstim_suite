# Pi 5 physical camera and combined display smoke — 2026-09-25

## Scope and safety boundary

This was a short physical-readiness test only. It did not use GPIO, reward,
water, suction, lick acquisition, telemetry, the experiment SSD, or a
behavioral session. No boot, compositor, persistent display, storage, or
camera configuration was changed.

The verified display roles remained:

| Role | DRM output | Connector | Physical display |
|---|---|---:|---|
| stimulus | `HDMI-A-2` | 42 | top-right visual-stimulus screen |
| preview | `HDMI-A-1` | 33 | bottom-left camera-monitor screen |

The cable trace remains corroborating evidence: physical HDMI0, the
micro-HDMI port nearest the USB-C power input, drives HDMI-A-1/33; the other
port drives HDMI-A-2/42.

## Priority A — physical photodiode

Deferred. Repository and audit documentation describe the software patch only:
bottom-right, 50 pixels, on value 255, off value 0, with even-frame-on and
odd-frame-off state. They do not identify an actual photodiode, DAQ, ADC, input
channel, GPIO input, cable, ground, or acquisition program. No physical input
or GPIO was guessed or touched.

## Priority B — simultaneous camera smoke

The installed native stack was used:

```text
rpicam-apps v1.11.1 02-02-2026
libcamera v0.7.0+rpt20260205
```

Stable identities were taken from the current `rpicam-hello --list-cameras`
enumeration, not from transient `/dev/videoN` names:

| rpicam index | identity | stable topology | result |
|---:|---|---|---|
| 0 | `imx708_noir` | `/base/axi/pcie@1000120000/rp1/i2c@88000/imx708@1a`, `platform:1f00110000.csi`, `/dev/media0` | concurrent 15 s capture, exit 0 |
| 1 | `imx708_wide_noir` | `/base/axi/pcie@1000120000/rp1/i2c@80000/imx708@1a`, `platform:1f00128000.csi`, `/dev/media4` | concurrent 15 s capture, exit 0 |

Each worker used `rpicam-vid`, no preview, 640x480 at 30 fps, and a temporary
H.264 output. Each output was approximately 3.8 MiB and was removed after the
test. The command did not transcode an existing recording. `rpicam-vid` did
not emit a capture-frame count in its default log, so counts are not claimed;
both workers remained alive through the samples and exited successfully.

Before/during/after resource observations:

| Observation | Result |
|---|---|
| before available RAM | about 1.4 GiB |
| during available RAM | about 1.3 GiB |
| before/during/after load | 0.00/0.00/0.06 to about 0.06/0.02/0.06 |
| peak temperature | 42.2 °C |
| throttling | `0x0` throughout |
| worker cleanup | no `rpicam-vid` processes remained |

The stable sensor identities were verified. Physical lens/camera placement
was not inferred from software enumeration because no safe physical camera
placement label was documented or required for this smoke.

## Priority C — combined display and camera smoke

One 3,600-frame (~60 s) production-renderer run was executed while both local
cameras captured concurrently. The display used the existing leased KMS path
and the corrected `HDMI-A-2` profile; no second KMS implementation was used.

Command roles:

```text
camera 0: imx708_noir
camera 1: imx708_wide_noir
display: hardware kms-render-smoke --frames 3600 --lease --json
mode: 1024x600 at the advertised 59.8214 Hz
format: RGB565
```

Display result:

| Metric | Result |
|---|---:|
| leased connector | HDMI-A-2 / 42 |
| lease objects | 42, 93, 104, 666 |
| excluded camera-monitor connector | HDMI-A-1 / 33 |
| requested/completed frames | 3,600 / 3,600 |
| selected mode | 1024x600@59.8214 |
| mean interval | 16,716.424 µs |
| p95 / p99 interval | 17,021.982 / 19,384.315 µs |
| min / max interval | 11,540.926 / 21,877.371 µs |
| effective refresh | 59.8214085 Hz |
| missed / estimated dropped frames | 0 / 0 |
| long / short intervals at 5% tolerance | 105 / 105 |
| page-flip errors/timeouts | 0 / 0 |
| lease restoration | `restored=true` |

The 210 out-of-tolerance intervals are real concurrent-load evidence, not
hidden by averaging. The complete native trace is
`pi5_phase3_combined_display_camera_2026-09-25.json`; resource samples are in
`pi5_phase3_combined_resources_2026-09-25.log`.

Resource samples during the combined run showed approximately 1.2 GiB
available RAM at the minimum, load up to 1.38, 45.0 °C peak temperature, and
`throttled=0x0`. Both camera outputs grew throughout the run and both workers
exited 0. The Pi reported labwc PID 756533 throughout the recovery checks;
both DRM connectors remained connected and no compositor process restart was
observed.

The software checks cannot observe the physical screens. The user should
confirm that the top-right stimulus display showed the alternating/renderer
pattern and that the bottom-left camera-monitor display stayed stable without
blanking or a compositor restart. No machine-observed abnormality was found.

## Priority D — controlled interruption and recovery

One short interruption was run with both camera workers genuinely active and
temporary `.h264` outputs. The display process was interrupted after startup;
the camera workers were then stopped through the test cleanup path. Results:

- display exit status: 0;
- both camera worker exit statuses: 0;
- no `rpicam-vid` workers or KMS probe process remained;
- labwc PID 756533 remained running;
- HDMI-A-1 and HDMI-A-2 remained connected;
- camera enumeration immediately succeeded for both stable identities;
- temporary outputs were removed.

The camera commands completed their bounded timeout lifecycle rather than
exiting immediately on the attempted SIGINT, so a production camera
supervisor still needs an explicit, measured stop path. This is a supervisor
follow-up, not evidence of a camera capture failure.

## Result and boundary

The Pi has now passed a short real simultaneous dual-camera smoke and a short
combined leased-display/two-camera resource test. This does not pass canonical
Gate 3. Physical photodiode timing, storage/SSD validation, a production
camera supervisor, clean timing under the eventual camera mode and storage
load, integrated GPIO/reward acceptance, and behavioral-session acceptance
remain open.
