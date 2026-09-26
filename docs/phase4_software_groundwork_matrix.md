# Phase 4 software-groundwork matrix

This is an implementation matrix, not a hardware acceptance checklist. A
software row becoming complete does not advance the hardware phase gate.

| Requirement | Current implementation | Safe software work now | Hardware validation later |
|---|---|---|---|
| Natural-image selection | Deterministic `SessionPlan` and golden tests | Resolve, decode, transform, and prepare frames with bounded caches | Compare rendered output and photodiode timing on the final screen |
| Arbitrary frame supply | Native path remains bounded two-frame smoke transport | Use `BoundedFrameTransport` and a producer-side sequence boundary | Implement/validate Linux shared-memory or native frame-table adapter |
| Asset policy | File discovery only was previously defined | Pillow-backed RGB conversion, explicit stretch/fit-pad/crop, hashes, errors | Confirm source corpus conversion and display geometry |
| Local dual cameras | Metadata-only fake service | Add independent worker supervision, bounded status, manifests, and failure cleanup | Resolve actual IMX708 identities, modes, capture tools, and output growth |
| Camera provenance | Basic fake status manifest | Record stable identity, command/mode, timestamps, exit and verification state | Validate real sensor/frame timestamps and negotiated modes |
| Production storage | Path inspection only | Add fail-closed mount, space, writeability, and identity-hook preflight | Identify SSD UUID/mount and run sustained dual-camera writes |
| Session outputs | Manifest, plan, events, resolved config, provenance | Add preflight, final status, display/camera/resource summaries | Validate retention and recovery under real interruption |
| Resource budget | Display-only estimates and Pi baseline | Parameterized bounded cache/queue estimates and checks | Measure RAM, thermal, disk, and display timing under full load |
| Timing analysis | Historical callback trace analysis | Analyze corrected kernel/callback/frame metadata with synthetic tests | Collect the corrected 300-frame leased trace |
| GPIO/reward | Simulated safe worker and pin validation | Clarify contracts and future orchestration boundaries | Validate pins, actuation, lick timing, and water limits |

The current branch does not claim physical photodiode, SSD, camera, GPIO, or
native Linux DRM acceptance.
