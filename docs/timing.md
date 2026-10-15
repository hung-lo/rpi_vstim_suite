# Timing model

`CLOCK_MONOTONIC` is authoritative for within-session ordering. `CLOCK_SYNC`
samples monotonic and realtime clocks and maps to UTC. Avoid ordering events
by formatted wall-clock text.

On validated KMS, kernel vblank/page-flip timestamps represent actual
presentation where available. Callback receipt is separate and is not
display time. Full trace is retained for long sessions. The Pi is not hard
real time: occasional extended or skipped refreshes occur. Reconstruct
presentation from recorded timestamps, not nominal 60 Hz.

Camera MP4 PTS is available. Per-frame camera hardware timestamps are not
claimed. IRIG physically captured by camera/DAQ can provide independent
absolute time for offline alignment. NeuroKairos is an optional external
service that may continuously provide IRIG-H; VStim does not control it.
Box151 reserves BCM GPIO9 for that sender.
