# Retinotopy

The retinotopy protocol preserves the adjacent black/white bar-pair stimulus
from frozen `rpi_visual_stimuli` commit
`6e1b2776e59c89127f9a6b56854096eb726990da`. It is implemented in the unified
protocol/session layer and has hardware-free plan, render, cache, direction,
frame-plan, and fake-display tests. Pi physical validation remains pending.

## Directions and sweep behavior

The default mode is two directions in fixed order:

1. `left_to_right` (azimuth)
2. `top_to_bottom` (elevation)

The optional four-direction profile enables `left_to_right`, `right_to_left`,
`top_to_bottom`, and `bottom_to_top`. The fixed order is retained by default;
`sequence_order_mode = "shuffled"` independently shuffles the enabled set
within each repeat using the saved seed.

Each sweep displays adjacent bars on gray. Horizontal sweeps use vertical bars;
vertical sweeps use horizontal bars. The black bar remains on the negative
screen-coordinate side and white on the positive side, including for reverse
sweeps. The leading color is white for left-to-right and top-to-bottom sweeps,
and black for the reverse sweeps. Bar width is 10% of the screen dimension
along the sweep axis. The
trajectory is linear in screen pixels, as in the historical protocol; it is
not warped for constant visual-angle velocity.

Historical defaults are 20 s sweep, 5 s gray after every sweep, 3 s initial
and final gray, 15 source movement frames/s, and 20 repeats/direction. At 60 Hz
each source frame is held for four refreshes. At the current nominal 59.82 Hz,
the deterministic cumulative-boundary schedule assigns three or four refreshes
per source frame (1,196 refreshes for 300 positions), preserving the intended
15 Hz source motion without assuming a 60.000 Hz display. Actual KMS timestamps
are retained for analysis. For the 20 s sweep, four source positions receive
three refreshes and 296 receive four; cumulative boundary rounding keeps each
position start within half a refresh of its nominal 15 Hz time.

## Frame plan for later 2P analysis

Every session writes `retinotopy_frame_plan.csv`. Each source movement row has:

- sweep/trial index, repeat, direction, axis, and source-frame index
- planned session-relative and sweep-relative onset, first and last nominal
  display-refresh indices, nominal refresh rate, and refresh count
- normalized travel position and normalized screen-boundary position
- nominal continuous and rendered integer boundary coordinates in pixels,
  plus unclipped and visible-clipped half-open black/white bar intervals in
  pixels
- screen dimensions, active width/height, eye distance, and screen-center convention
- derived planar screen coordinates in cm and degrees of visual angle
- actual first KMS kernel/callback timestamp when the current display result exposes it

Pixel coordinates start at the top-left pixel center, with X increasing right
and Y increasing down. Screen-plane coordinates use the pixel-grid center as
the physical origin, with X increasing right and Y increasing up. Positive
visual-angle X is rightward and positive visual-angle Y is upward. Saved bar
edge intervals are half-open `[start, end)`; visible intervals are clipped to
the screen bounds.

The session also contains `screen_geometry.json`, `plan.json`,
`kms_timing_trace.json`, and the cache/render manifest. A movement position
persists for the `refresh_count` consecutive display refreshes listed in the
CSV. Together with the KMS trace, this lets an offline analysis map neural
samples to the scheduled stimulus position without reverse-engineering the
renderer. Geometry comes from the rig profile, not protocol constants.

The CSV's KMS timestamps are software display timing. They are not
photodiode-measured physical onset; photodiode calibration remains pending.
There is no protocol TTL assignment. GPIO9 remains reserved for NeuroKairos,
and no other GPIO output is claimed by retinotopy.

## Preview, cache, and short smoke

The preview shows start, middle, and end frames for every enabled direction and
does not need Pi hardware:

```bash
rpi-vstim retinotopy preview \
  --config config/rigs/visual_mapping_simulation.toml \
  --protocol-config config/protocols/retinotopy.4dir-smoke.toml \
  --output /tmp/retinotopy-4dir.png
```

Install NumPy/Pillow with `python -m pip install -e '.[visual]'`. Pre-render
and validate cache data before a run:

```bash
rpi-vstim retinotopy build-cache \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --protocol-config config/protocols/retinotopy.smoke.toml \
  --cache-root /mnt/behavbox_ssd/visual_cache
```

Two-direction Pi smoke, one short sweep per direction:

```bash
rpi-vstim retinotopy run \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --protocol-config config/protocols/retinotopy.smoke.toml \
  --cache-root /mnt/behavbox_ssd/visual_cache \
  --output-root /mnt/behavbox_ssd/sessions \
  --cameras
```

Four-direction direction-label check:

```bash
rpi-vstim retinotopy run \
  --config config/rigs/pi5_natural_image_demo.example.toml \
  --protocol-config config/protocols/retinotopy.4dir-smoke.toml \
  --cache-root /mnt/behavbox_ssd/visual_cache \
  --output-root /mnt/behavbox_ssd/sessions \
  --cameras
```

Each smoke stimulus schedule is approximately 3–4 seconds, plus camera startup
and finalization. Visually confirm every direction and inspect the frame-plan
to KMS-index mapping. These commands are prepared for Pi validation; no physical
validation is claimed yet.
