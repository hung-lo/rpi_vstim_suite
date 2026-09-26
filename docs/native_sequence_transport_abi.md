# Native sequence transport boundary

The software adapter in `rpi_vstim.display.transport` defines the later native
ABI without requiring DRM headers on the Mac. A producer submits contiguous
`producer_sequence` values and immutable packed payloads. The consumer obtains
a lease, owns the slot until acknowledgement, and then releases the slot for
reuse. `capacity` bounds ready plus in-flight slots; `finish` drains to EOF and
`abort` clears immediately with a reason.

The native implementation should preserve these invariants:

1. producer sequence numbers are contiguous and reject stale/replayed frames;
2. payload byte count matches the declared packed format and dimensions;
3. producer blocking has a bounded timeout and never allocates an unbounded
   queue;
4. consumer acknowledgement is idempotent;
5. abort wakes both sides and prevents later publish/consume; and
6. display timing metadata is carried beside the payload, never inferred from
   slot order after a drop.

The existing native DRM code remains hardware-specific. A Pi build must still
validate the actual dumb-buffer/GBM import path, page-flip completion, connector
ownership, and recovery after an interrupted consumer.
