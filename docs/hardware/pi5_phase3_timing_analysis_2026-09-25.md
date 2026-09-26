# Pi 5 Phase 3 combined display/camera timing analysis — 2026-09-25

This is a hardware-independent analysis of the committed trace from the
combined HDMI-A-2 leased production-renderer run with both local cameras:

`docs/hardware/pi5_phase3_combined_display_camera_2026-09-25.json`

The raw trace and the dated hardware report are unchanged. This note analyzes
their recorded software flip-callback timestamps; it does not replace physical
photodiode validation.

## Recomputed trace facts

The trace contains 3,600 page-flip events and 3,599 intervals. Using adjacent
`monotonic_ns` values, the report's nominal `59.8214286 Hz` refresh gives an
expected interval of `16,716.418 µs`; the 5% classification boundaries are
`15,880.597–17,552.239 µs`.

| Measure | Result |
|---|---:|
| mean interval | `16,716.424 µs` |
| minimum / maximum | `11,540.926 / 21,877.371 µs` |
| out of tolerance | `210` |
| long / short | `105 / 105` |
| missed / estimated dropped frames | `0 / 0` |
| kernel-sequence gaps | `0` |
| frame-index gaps | `0` |
| lease restoration | `true` |

Every long interval is immediately followed by a below-nominal interval, and
every short interval is immediately preceded by an above-nominal interval.
For each of the 105 long intervals, the two-interval sum is between
`33,378.259` and `33,451.908 µs`, with a mean of `33,430.756 µs`; two nominal
refresh periods total `33,432.836 µs`. Two partner intervals fall just inside
the 5% classification boundary, which is why the exact threshold pairing is
104 while the adjacent compensation pattern covers all 105 long/short counts.

## Interpretation and limits

The trace is consistent with 105 adjacent long/short timing displacements
rather than 210 independent missed refresh periods. The contiguous kernel
sequence, contiguous frame index, zero native missed/dropped counts, and
near-two-refresh pair sums support that interpretation. It still records
real timing excursions under simultaneous camera load. The operator's report
of possible brief flashes therefore remains valid evidence for follow-up, not
something this software trace can dismiss.

These are software timestamps from page-flip callbacks. Without a photodiode,
they cannot establish luminance onset, visible flicker, or the final-screen
optical result. The final stimulus screen may also change later.

## Next validation gate

When hardware access is available again:

1. identify and mount the experiment SSD by device/UUID; never use the Pi SD
   card as production-storage acceptance;
2. repeat the trace with sustained writes from both camera workers to the SSD;
3. compare camera-off, dual-camera, and dual-camera-plus-SSD timing/resource
   runs using the eventual camera mode; and
4. validate physical onset with the available photodiode on the final screen.

The analysis is covered by
`tests/integration/test_phase3_trace_artifact.py` and requires no Pi, SSH,
camera, GPIO, or display access.
