# Real natural-image demo

The first integrated real-Pi demonstration is intentionally a composition of
the existing natural-image planner, continuous leased KMS renderer, dual lick
monitor, camera supervisor, session output, and bounded event handoff. It is a
demo/validation runner, not the final production animal-data session runner.

From the repository checkout:

```text
rpi-vstim natural-images run \
  --mouse-id V1_2 \
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

Each session is written below the explicit demo output root in the config and
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

The current runner has not accepted final SSD storage, optical photodiode
timing, or full production-session semantics. Those remain separate validation
gates.
