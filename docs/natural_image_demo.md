# Real natural-image demo

The first integrated real-Pi demonstration is intentionally a composition of
the existing natural-image planner, continuous leased KMS renderer, dual lick
monitor, camera supervisor, session output, and bounded event handoff. It is a
demo/validation runner, not the final production animal-data session runner.

On the production Pi, the bundled profile writes directly to the mounted NVMe
filesystem at `/mnt/behavbox_ssd/sessions` (not to the checkout or SD card):

```text
rpi-vstim natural-images run \
  --mouse-id V1_2 \
  --output-root /mnt/behavbox_ssd/sessions \
  --licks \
  --cameras \
  --camera-preview
```

The default demo configuration is
`config/rigs/pi5_natural_image_demo.example.toml`. It selects 20 images from
the real 2,800-image corpus using the existing `natural_legacy_plain` plan and
the existing `crop` preparation policy. Use `--image-count 2800` for the full
corpus; that is a long run. No reward calibration or reward output is loaded.

Display and GPIO policy:

- HDMI-A-2 / DRM connector 42 is the leased stimulus display.
- HDMI-A-1 / DRM connector 33 remains compositor-owned for the camera monitor.
- Only BCM26 (`lick_left`) and BCM27 (`lick_right`) are acquired.
- Raw lick edges and classified licks are separate `LICK_RAW_EDGE` and `LICK`
  records. GPIO15, GPIO23, GPIO9, and every reward/vacuum/airpuff/trigger line
  remain untouched.

Both cameras record with stable topology identities at 640x480, 30 fps, H.264,
and no raw stream. With `--camera-preview`, the same `rpicam-vid` processes use
the installed native preview option:

```text
camera 0: --preview 0,0,512,384
camera 1: --preview 512,0,512,384
```

The preview is operator-only and non-scientific. It does not take KMS/DRM
ownership of HDMI-A-1. Recording takes priority over preview. The optional
rpicam ROI/crop feature is intentionally deferred; the demo does not add a
software crop, decoder, or re-encoder path.

Each session is written below the explicit output root in the config (or its
`--output-root` override) and
contains the current repository artifacts, including `plan.json`,
`asset_manifest.json`, `camera_manifest.json`, `display_results.json`,
`provenance.json`, and `final_status.json`. The authoritative integrated event
timeline is `events.jsonl`. Every event contains `schema_version`, `event`,
`session_id`, UTC ISO-8601 `utc_time`, derived `utc_ns`, source/authoritative
`monotonic_ns`, and `session_elapsed_s`. The first records include `SESSION_START`
and `CLOCK_SYNC`.

Lick timestamps are the lgpio alert timestamps. Display boundary records use
the retained DRM callback timestamp trace when available, with an explicit
fallback marker if only a planned timestamp can be derived. Camera lifecycle
records do not claim per-frame timing; detailed recording status belongs in
`camera_manifest.json`.

Ctrl-C stops the KMS sequence, restores the stimulus display, releases both
lick callbacks, reaps both camera processes, flushes the bounded event writer,
and finalizes the session. A clean second run should be possible immediately.

The runner now accepts direct SSD session output. Optical photodiode timing and
the broader production-session protocol remain separate validation gates.

## Production storage policy

`/mnt/behavbox_ssd/sessions` is validated before the runner creates session
artifacts or acquires KMS, cameras, or GPIO. It must be a writable mount of
`/dev/nvme0n1p1`, formatted as ext4 with UUID
`18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99`, and have at least 20 GiB free. A failed
check aborts; it never falls back to `demo_sessions`, `/tmp`, the home
directory, or the SD card. Storage identity and free space are captured at
session start and end in `provenance.json` and `final_status.json`.
