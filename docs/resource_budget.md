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

The software-only display bounds now include two reusable scanout buffers and
an eight-entry LRU frame cache. At 1024x600 this is approximately:

| Format | Two scanout buffers | Full eight-frame cache | Renderer total |
|---|---:|---:|---:|
| RGB565 | 2,457,600 B / 2.34 MiB | 9,830,400 B / 9.38 MiB | 12,288,000 B / 11.72 MiB |
| XRGB8888 | 4,915,200 B / 4.69 MiB | 19,660,800 B / 18.75 MiB | 24,576,000 B / 23.44 MiB |

These are packed pixel payloads and exclude Python object/file-system overhead;
the cache is bounded and frame preparation occurs before page flips. The
display-only renderer therefore fits comfortably within the Pi's 2 GB RAM
budget, while camera buffers and concurrent capture remain unmeasured.

The 10,000-frame A2 hardware run used the existing two native dumb buffers.
The production-renderer smoke used two prepared cached frames and no unbounded
image accumulation. The real Pi timing report is not integrated camera or
production-storage acceptance.

Production storage and concurrent camera-write measurements remain deferred
until the experiment SSD is attached. Temporary test directories must not be
used as evidence for the future experiment SSD or as a fallback recording root.

## SSD-backed validation preparation

The next storage gate is hardware-only and must be run on the Pi after the SSD
is physically connected:

1. record the device, filesystem UUID, intended mount point, and existing
   `/etc/fstab` intent;
2. verify the mounted filesystem is the SSD, writable, and has sufficient free
   space; do not accept `/` or the SD card as a substitute;
3. run a bounded write/read throughput check in a disposable SSD test path;
4. record sustained output growth from both camera workers; and
5. repeat leased display + dual-camera + SSD-write load while recording RAM,
   CPU/load, temperature, throttling, page-flip timing, cleanup, and free space.

The current combined display/two-camera resource log is a no-SSD baseline only:
about 1.2 GiB minimum available RAM, load up to 1.38, 45.0 °C peak, and
`throttled=0x0`. It is not SSD or production-storage acceptance.
