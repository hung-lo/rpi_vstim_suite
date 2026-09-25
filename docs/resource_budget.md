# Software-groundwork resource budget

The overnight implementation is intentionally metadata-only and bounded:

- telemetry uses an in-memory deque capped at 256 packets;
- fake camera services retain one status record per configured camera and no
  frame buffers;
- protocol plans retain event metadata and frame counts, never decoded pixels;
- session writes are streaming JSON/CSV artifacts rather than an in-memory
  image or camera cache;
- seeded planners use local `random.Random` instances and do not consume the
  process-global random stream.

The Pi 5 audit records 2 GB RAM. Real display buffers, decoded stimulus cache,
camera-worker queues, concurrent capture load, GPIO workers, and network
telemetry must be measured on the Pi before any hardware phase. Those checks
are deferred hardware validation and are not inferred from desktop tests.

The software-only bounds currently established are the 256-message telemetry
deque, one metadata record per fake camera, and no decoded-frame retention in
the fake runtime. The read-only display probe parses command output only; the
separate native smoke path allocates two bounded display buffers and reports
their timing, but is not a production resource-budget acceptance.

Production storage and concurrent camera-write measurements remain deferred
until the experiment SSD is attached. Temporary test directories must not be
used as evidence for the future experiment SSD or as a fallback recording root.
