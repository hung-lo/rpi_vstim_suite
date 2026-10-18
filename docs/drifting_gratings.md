# Drifting gratings

Drifting gratings are implemented in the unified `rpi-vstim` protocol layer.
The reference is the frozen `rpi_visual_stimuli` commit
`6e1b2776e59c89127f9a6b56854096eb726990da`. Software tests cover planning,
rendering, caching, previews, session output, and fake-display execution. Pi
physical validation remains pending.

## Stimulus and orientation convention

The default is a full-screen sinusoidal grating with bar-axis orientations
`0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5` degrees. `bar_orientation_deg`
describes the axis of the bars. `drift_direction_deg` describes motion and is
`(bar_orientation_deg - 90) mod 360`: horizontal bars at 0 degrees drift at
270 degrees; vertical bars at 90 degrees drift at 0 degrees. Both are recorded
per trial and shown on the labeled preview sheet.

Historical defaults are 80 trials per orientation, 0.5 s stimulus, 0.7 s ITI
plus independent uniform jitter in `[0, 0.5)` s, 2 Hz temporal frequency, 0.2
cycles/cm spatial frequency, Michelson contrast 1.0, mean luminance 0.5, and
3 s initial and final gray. Trial order is shuffled with a local seeded
generator while repeats remain balanced. The resolved seed and every planned
trial and ITI are written to the session. The unified interface defaults to a
fixed seed (`0`) unless a config or `--seed` supplies another value. The frozen
runner chose a time-derived seed when none was supplied; using a fixed default
is an intentional reproducibility difference.

Spatial frequency remains in cycles/cm for compatibility. The active screen
geometry, pixel pitch, eye distance, and calibration ID are snapshotted so
offline analysis can derive visual-angle geometry later. No cycles/degree mode
is currently defined. An optional rectangular patch mode uses explicit
center/width/height values in screen-plane cm.

The carrier uses separate physical X and Y screen-plane coordinates before
projection onto the orientation normal; it does not use one X-derived scale or
assume square pixels. On the configured 1024×600 OL7 geometry (15.50×8.72 cm),
pixel pitches differ by about 4.15%, but the computed carrier remains 0.2
cycles/cm at 0°, 45°, and 90°.

Durations are quantized to the nearest configured display refresh. For example,
0.5 s at 59.82 Hz plans 30 frames (about 0.5015 s). Grating phase advances by
the configured temporal frequency and nominal refresh; each trial starts at
the configured starting phase. KMS kernel timestamps remain the software
display timing reference. The 30-refresh interval advances 360° at 60 Hz and
361.083° at 59.82 Hz; the last sampled phase at 59.82 Hz is 349.047°.

## Preview and cache

Install the optional rendering dependencies with
`python -m pip install -e '.[visual]'`. Preview works without a Pi, KMS,
cameras, or GPIO:

```bash
rpi-vstim drifting-gratings preview \
  --config config/rigs/visual_mapping_simulation.toml \
  --protocol-config config/protocols/drifting_gratings.smoke.toml \
  --output /tmp/drifting-gratings.png
```

Build and validate the packed display-frame cache before acquisition:

```bash
rpi-vstim drifting-gratings build-cache \
  --config config/rigs/visual_mapping_simulation.toml \
  --protocol-config config/protocols/drifting_gratings.smoke.toml
```

The preview labels each bar orientation and drift direction. Its magenta arrow
marks motion direction for inspection only; the arrow is not part of any
stimulus frame.

Cache identity covers display geometry/format, photodiode settings, and all
scientific render parameters. The cache has per-frame-set SHA256 checksums and
is revalidated before `run`; stimulus generation does not happen in the KMS
playback loop.

## Outputs

The standard session includes `plan.json`, `events.jsonl`, `display_results`,
`kms_timing_trace.json`, session provenance, and integrity status. The
protocol-specific `drifting_grating_trial_plan.csv` includes condition,
repeat, bar orientation, drift direction, phase/frequency/contrast/luminance,
frame count, requested and quantized ITI, cache key, and cache-frame checksum.
The cache manifest and labeled orientation contact sheet remain in the cache
directory referenced by the session.

`STIMULUS_PRESENTATION_START/END` events link planned frames to KMS trace frame
indices and actual kernel timestamps when exposed. The display request time is
not physical monitor onset. Photodiode measurement is still required for
physical visual-onset calibration.

## Short Pi smoke

The smoke config presents all eight orientations once. On the Pi, build the
cache once, then run both cameras and the current KMS profile:

```bash
rpi-vstim drifting-gratings build-cache \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --protocol-config config/protocols/drifting_gratings.smoke.toml \
  --cache-root /mnt/behavbox_ssd/visual_cache

rpi-vstim drifting-gratings run \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --protocol-config config/protocols/drifting_gratings.smoke.toml \
  --cache-root /mnt/behavbox_ssd/visual_cache \
  --output-root /mnt/behavbox_ssd/sessions \
  --cameras
```

The visual schedule is about 9 seconds plus camera startup/finalization. Check
that all eight labeled orientations appear, the session is `COMPLETE`, the
full KMS trace is present, both camera QC results pass, and event drops/errors
are zero. NeuroKairos can continue independently; GPIO9 is never acquired.
