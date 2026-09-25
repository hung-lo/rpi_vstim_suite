# KMS display native boundary

The Python Phase 3 slice currently performs read-only connector/mode discovery
through `modetest` and keeps presentation fail-closed. This directory remains
the native boundary for the later synchronous page-flip implementation.

The native layer must eventually open only the configured stimulus connector,
select the requested mode, use bounded buffers and page-flip events, emit
monotonic/realtime timing records, apply the configured photodiode patch, and
restore the original CRTC on normal exit or interruption. No production
backend, full-screen test, or timing acceptance is claimed by the current
Python work.
