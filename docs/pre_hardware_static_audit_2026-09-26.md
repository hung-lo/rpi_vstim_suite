# Pre-hardware static production-path audit

The audit uses repository search plus targeted source review. Matches are
classified instead of treated as defects automatically.

| Match | Classification | Action |
|---|---|---|
| `native/kms_display/kms_probe.c` `/dev/dri` | Linux native boundary | Hardware-only probe; no desktop path opens it |
| Camera supervisor `/dev/videoN` text | Safety documentation | Stable identity is required; transient nodes are never configured |
| `subprocess` in camera/native diagnostics | Explicit process boundary | Arguments are tuples/argv; stdout/stderr are bounded or captured |
| `deque`/`Queue` | Bounded transport | Display, camera status, telemetry, and GPIO queues have capacities |
| `while True` in transport/emulator | Lifecycle loop | Ends on finish/abort or is test-only fake-camera behavior |
| `except Exception` in runtime cleanup | Failure containment | Every service cleanup is attempted; errors are retained in final status |
| `tempfile` | Tests and KMS diagnostic frame bridge | Never used as production storage; storage preflight rejects temp roots |
| `Path.home` and `/tmp` | Storage safety checks/tests | Explicitly rejected as production recording roots |
| `NotImplementedError` | Hardware/Phase 00 import boundary | Intentional; no silent simulation fallback |
| `signal`/`sleep` | Camera supervision and emulator | Bounded startup/stop deadlines; no production timing acceptance implied |

No `shell=True`, SSH invocation, process-global random source, or new
unbounded production queue was found. The native DRM and camera commands are
still Pi/Linux gates; static review cannot establish runtime acceptance.
