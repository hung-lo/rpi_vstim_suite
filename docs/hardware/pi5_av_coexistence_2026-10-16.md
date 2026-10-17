# Pi 5 visual and USB-audio coexistence — 2026-10-16

## Purpose

This engineering run checked simultaneous operation of natural-image KMS
presentation, both local Pi cameras, session event logging, direct NVMe
recording, the external NeuroKairos IRIG-H service, and persistent preloaded
USB audio.

## Source and session

- Session: `av-coexistence-replay3-20261016211709Z`
- Session directory: `/mnt/behavbox_ssd/sessions/av-coexistence-replay3-20261016211709Z`
- Repository source recorded in `final_status.json` and `provenance.json`:
  `dc3cdd2855cdde8574f23bdcd73d9df522fd513e`
- Source branch at validation: `codex/audio-vstim-coexistence`
- The integration runner was committed at that SHA. The exact commit was
  archived from WSL and run from a temporary Pi directory; no uncommitted
  validation script was involved and `/home/pi/rpi_vstim_suite` was untouched.

The session lifecycle spanned 123.974 s. The planned visual duration was
120.645 s, and the first-to-last retained KMS kernel presentation timestamps
spanned 120.626 s. The visual seed was `0`; 84 selected natural images produced
7,217 requested frames at the configured 59.82 Hz mode.

## Results

| Subsystem | Recorded result |
|---|---|
| USB audio device | Unique `USB Audio Device` match selected (C-Media / Unitek Y-247A; observed as `hw:2,0` on this run) |
| Audio schedule | 8 requested: beep, buzz, white noise, beep, buzz, white noise, beep, buzz; offsets 10, 25, 40, 55, 70, 85, 100, 115 s |
| Audio completion | 8 callback starts; 0 missed; 0 duplicate requests/callbacks; 0 callback status errors |
| Request-to-callback latency | median 3.452 ms; mean 3.945 ms; SD 2.901 ms; min 0.151 ms; p95 7.923 ms; max 7.923 ms |
| Visual presentation | 7,217 requested / 7,217 completed; all 7,217 trace records retained; trace not truncated |
| KMS timing | 0 missed vblanks; 0 extended intervals; mean interval 16.717 ms; p95 17.379 ms; max 17.382 ms; display restored successfully |
| Camera `imx708_noir` | Exit 0, graceful stop, fast QC PASS; 122.612 s MP4 at 30.013 fps; scientific interval covered |
| Camera `imx708_wide_noir` | Exit 0, graceful stop, fast QC PASS; 121.746 s MP4 at 30.013 fps; scientific interval covered |
| Event writer | 302 events written; 0 drops; 0 errors; queue high-water mark 256 / 4,096 |
| Session integrity | `COMPLETE`; required files present; no missing or corrupt artifacts reported |
| Storage | Direct production output on `/dev/nvme0n1p1` (ext4); 953,123,246,080 bytes free at start and 953,103,159,296 bytes at end |

The fast camera QC checks container/stream metadata; it does not decode every
frame. Both files and coverage metadata passed that bounded check.

## System state

`irig-sender.service` reported active before, during, and after acquisition.
Post-run Chrony tracking reported stratum 2 and system time 5.660 µs fast of
NTP. Sampled temperatures were 49.9 °C and 51.0 °C during the run and 47.7 °C
after it. `vcgencmd get_throttled` remained `0x0`; the output filesystem
remained mounted on the NVMe volume with about 888 GiB free. Reward, vacuum,
airpuff, lick inputs, GPIO23, and reserved GPIO9 were not used by this run.

## Physical observation and interpretation

The operator's phone video qualitatively showed natural-image visual
stimulation and audible speaker output, with eight sounds in the logged
beep/buzz/white-noise sequence. This is physical confirmation of audible output
during visual stimulation only. The phone recording does not measure
command-to-speaker latency, audiovisual synchronization, calibrated acoustic
onset, or sound pressure level.

**Full-stack visual + USB-audio coexistence passed in this approximately
two-minute integration run.** This is an integration/coexistence validation,
not a dedicated long-duration audio endurance test. The `AUDIO_CALLBACK_START`
time records when the software output callback begins consuming PCM; it is not
physical acoustic onset. Audio SPL calibration at the mouse position, physical
acoustic-onset calibration, photodiode visual-onset calibration, downstream
acquisition-device IRIG validation, and final animal-facing water calibration
remain pending.
