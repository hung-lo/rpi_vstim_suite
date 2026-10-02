# Pi 5 lick-input characterization — 2026-09-30

## Scope

Only the physically connected channels were tested:

| Channel | BCM GPIO | Status |
|---|---:|---|
| lick_left | 26 | Tested |
| lick_right | 27 | Tested |
| lick_center | 15 | **NOT CONNECTED / NOT PHYSICALLY VALIDATED** |

GPIO15 was inspected read-only with `gpioinfo`; it was not requested,
configured, or included in either lick test phase. No conclusion about a
center lick detector is made here.

The capture used `lgpio` raw both-edge alerts with no debounce and no pull
configuration on GPIO26 and GPIO27.

## Physical characterization

Procedure: approximately 10 seconds idle, approximately 20 LEFT activations
with RIGHT untouched, a 2-second pause, then 20 RIGHT activations with LEFT
untouched. The activation counts below are the operator-reported counts.

| Measure | lick_left / GPIO26 | lick_right / GPIO27 |
|---|---:|---:|
| Idle level | 0 | 0 |
| Active level | 1 | 1 |
| Physical activation count | 20 | 20 |
| Raw transition count | 307 | 278 |
| Minimum observed callback spacing | 1.574 µs | 1.574 µs |
| Edges under 20 ms | 267 | 238 |
| Edges under 100 ms | 269 | 238 |
| Maximum edges in a 100 ms window | 18 | 18 |
| Untouched-channel cross-talk | 0 edges on GPIO27 | 0 edges on GPIO26 |
| Final level | 0 | 0 |
| Returned to idle | Yes | Yes |

Both connected inputs showed substantial multiple-edge/bounce behavior:
approximately 15.35 raw transitions per LEFT activation and 13.9 per RIGHT
activation. Both channels showed both raw levels, returned to idle after the
phase, and had zero sampled idle transitions during the initial 10-second
baseline. No stuck-level behavior was observed.

## Classifier settings and semantics

The classifier configuration is:

- `MIN_CLASSIFIED_LICK_INTERVAL_MS = 70`
- `RELEASE_STABLE_MS = 25`

The 25 ms release window is based on the recorded bursts: 267/307 LEFT
inter-edge gaps and 238/278 RIGHT gaps were under 20 ms; RIGHT had no gaps in
the 20–100 ms band, and LEFT had only two. The extra 5 ms provides a small
margin over the measured sub-20 ms bounce band without approaching the
70 ms physiological interval guard. Both manual activation series were spread
well beyond these intervals.

Raw GPIO edges remain preserved as their own timestamped stream. A classified
lick is emitted only on the first rising edge after a continuously LOW
`RELEASE_STABLE_MS` interval; the contact then latches, ignores bounce, and
re-arms only after LOW stability. A rising edge is also suppressed when it is
less than `MIN_CLASSIFIED_LICK_INTERVAL_MS` after the previous classified lick
on that channel. Raw rising-edge count is not used as the lick count.

## Integrated display + dual-camera + lick smoke

The short integrated run used only GPIO26 and GPIO27 while starting both
`rpicam-vid` workers and the leased display renderer.

| Result | Observation |
|---|---|
| Camera 0 | Exit 0; 1,998,582-byte H.264 output |
| Camera 1 | Exit 0; 2,018,568-byte H.264 output |
| Display renderer | Exit 0; 600-frame leased smoke |
| Raw lick edges | GPIO26: 218; GPIO27: 172 |
| Final lick levels | GPIO26: 0; GPIO27: 0 |
| GPIO15 | Not requested or configured; not tested |

Temporary outputs were written under `/tmp/rpi-vstim-integrated-lick-e8k9gj5z`
on the Pi.

## Classified dual-input validation — 2026-10-02

The production input monitor now owns BCM26 and BCM27 together, records every
raw both-edge alert, and classifies at most one event per released contact
burst. The canonical configuration is:

| Channel | BCM GPIO | Idle | Active | Release stable | Minimum classified interval |
|---|---:|---:|---:|---:|---:|
| lick_left | 26 | LOW | HIGH | 25 ms | 70 ms |
| lick_right | 27 | LOW | HIGH | 25 ms | 70 ms |

The first separated software run exposed and fixed a state-machine bug: the
initial idle timestamp could be reused as the first release timestamp. The
recorded raw traces replayed as 20 LEFT and 20 RIGHT after the fix. A fresh
physical validation then passed:

| Run | Classified | Raw edges | Cross-talk | Final level | Released |
|---|---:|---:|---:|---|---|
| LEFT on GPIO26 | 20 | 289 | 0 | LOW on both | Yes |
| RIGHT on GPIO27 | 20 | 256 | 0 | LOW on both | Yes |

Both runs used the corrected classifier with no reward/vacuum output access;
GPIO15 was not requested, configured, or touched. Raw edges and classified
events were written to separate JSONL streams, and callback errors were empty.

## Integrated display/camera smoke — 2026-10-02

A short run also started the leased display renderer and both camera workers
while the dual lick monitor held BCM26/27. The completed display portion used
HDMI-A-2 / connector 42 for 300 frames and reported:

- contiguous frame and kernel sequences;
- zero missed, dropped, doubled, short, or long intervals;
- one lease acquire, one modeset, one restore, and one lease release;
- final display restoration successful;
- photodiode metadata valid.

The cameras produced H.264 output (974,848 and 942,080 bytes). No physical
lick contacts occurred during this integrated smoke window, so its raw and
classified lick counts were both zero; this does not claim physical integrated
event logging acceptance. The separate dual-input monitor test and the 20/20
physical runs verify the raw/classified stream separation and classification.
