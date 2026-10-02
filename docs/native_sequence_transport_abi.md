# Native sequence transport boundary

The software adapter in `rpi_vstim.display.transport` defines the frame-state
boundary without requiring DRM headers on the Mac. A producer submits
contiguous `producer_sequence` values and immutable packed payloads. The
native KMS adapter consumes the same states through a bounded pipe-backed
producer queue and keeps one DRM lease/modeset alive until EOF or interruption.
`capacity` bounds the software transport; the native stream queue is fixed at
32 packed frames.

The native implementation should preserve these invariants:

1. producer sequence numbers are contiguous and reject stale/replayed frames;
2. payload byte count matches the declared packed format and dimensions;
3. producer blocking has a bounded timeout and never allocates an unbounded
   queue;
4. consumer acknowledgement is idempotent;
5. abort wakes both sides and prevents later publish/consume; and
6. display timing metadata is carried beside the payload, never inferred from
   slot order after a drop; and
7. ordinary gray/image boundaries never restore or release the compositor.

The native DRM code remains hardware-specific. A Pi build must still validate
the actual dumb-buffer path, page-flip completion, connector ownership,
continuous frame/index/kernel-sequence accounting, and recovery after an
interrupted consumer.
