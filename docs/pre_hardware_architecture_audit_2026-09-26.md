# Pre-hardware architecture audit

Audit baseline: branch `codex/pre-hardware-rc-hardening`, parent `15cd7ab`.
The audit is software-only; no Pi, camera, SSD, GPIO, DRM device, or
photodiode was accessed.

| Subsystem | Purpose / public boundary | Lifecycle and failure behavior | Bounds / hardware gate | Coverage / risk / cleanup |
|---|---|---|---|---|
| Configuration | TOML-to-frozen-dataclass schema via `Config`, `load_config`, `config_from_mapping` | Validate before simulation or hardware commands; malformed sections fail closed | No hardware access; production paths and stable camera identity remain gates | Unit and CLI tests; legacy `gpio` alias is compatibility surface |
| CLI | `rpi_vstim` commands for simulation, virtual rig, preflight, inspection, display/native probes | Returns nonzero on invalid config or failed command; hardware commands are explicit | Dry-run and virtual-run are hardware-free; native probes require Pi/Linux devices | Contract and virtual-rig tests; write-heavy lab runner is separate |
| Protocol planning | Five deterministic `build_plan` implementations returning `SessionPlan` | Pure plan construction; invalid settings raise | Event metadata bounded by plan size; protocol behavior is software-testable | Unit/integration/golden tests; reward panel persistence remains separate |
| Assets | `AssetResolver`, `AssetManifest`, `AssetPreparer` | Preflight resolves and fingerprints sources; mutation fails preparation | Cache/transport bounded; actual image corpus and Pi storage are gates | Manifest/cache tests; Pillow is optional dependency |
| Frame transport | `BoundedFrameTransport`, `PrefetchCoordinator`, display sequence adapter | Finish drains to EOF; abort wakes and fails fast; producer is reaped | Capacity, watermarks, and immutable payloads are explicit | Threaded tests; native adapter is in-memory until Linux/DRM build |
| Display abstraction | `DisplayBackend`, fake backend, KMS backend, renderer, timing analysis | Open/present/close; KMS errors propagate; fake backend drives desktop runs | KMS ownership, connector/mode, page-flips, photodiode are hardware gates | Display and trace tests; KMS module imports temp-file paths that need audit |
| Native display bridge | `native/kms_display` probe, lease code, frame semantics | C self-tests are portable; DRM runtime is device-dependent | libdrm/Wayland headers and `/dev/dri` are Linux/hardware-gated | Native frame self-test; Linux build must be repeatable |
| Camera identity | `CameraIdentity` → `EnumeratedCamera` → `ResolvedCamera` | Missing/duplicate/family mismatch fails closed | Stable topology and runtime selector require Pi enumeration | Fixture tests; `core.camera_identity` is a duplicate legacy module |
| Camera supervision | `LocalCameraSupervisor`, bounded status channel, local subprocesses | Start growth deadline, poll/stall, graceful stop, kill/reap, manifest | Per-camera files and actual rpicam selector/mode are hardware-gated | Fake subprocess and supervisor tests; command contract awaits Pi validation |
| Storage | `inspect_storage`, `preflight_storage`, storage session/finalize | Unsafe roots fail; incomplete marker retained until required files exist | Mount/device identity and SSD throughput are hardware-gated | Temp-path fault tests; mount readers are still fixture-only |
| Session lifecycle | `SessionOutput`, atomic artifacts, `inspect_session`, canonical digest | Begins incomplete; final status cannot overwrite cleanup failure; corrupt/future artifacts are rejected | JSONL/summary/session marker bounded; power-loss behavior only simulated | Integration, inspection, crash campaign, and digest tests; hard-kill remains a hardware/filesystem gate |
| Telemetry | Schema/payloads plus `InMemoryTelemetryPublisher` | Publish is nonblocking/bounded; required failure is explicit | No network in desktop path; monitor compatibility remains fixture-only | Envelope and stress tests; no persisted telemetry artifact yet |
| GPIO/reward | Typed command/event contract and simulated worker | Safe/stop idempotence, duplicate command suppression, water cap | Pin polarity, pulse timing, lick/reward hardware are gates | Contract tests; spawned production worker is intentionally absent |
| Resource budget | `estimate_budget` returns explicit RAM/storage bound | Invalid negative inputs reject; report is advisory | Real Pi RAM/load/temp/storage remain gates | Unit and dry-run coverage |
| Provenance | `collect_provenance`, session config/source metadata, canonical session digest | Written at session start; timestamps are nondeterministic and removed from replay digests | Host identity is recorded, not validated | Serialization and digest tests; hardware provenance remains deferred |
| Timing analysis | Generic flip trace summaries and metadata validation | Malformed/insufficient traces produce explicit analysis | Physical 105-long/105-short interpretation and photodiode remain gates | Phase 3 trace tests; historical traces are immutable |
| Tests/scripts/docs | Fast pytest suite plus separate stress, campaign, CI, and lab docs | Fast suite stays short; heavy commands are opt-in | Hardware scripts are preparation only | 201-test suite; heavy soak/RC campaigns and docs navigation are present |

## Cross-cutting findings

- Ownership is explicit through `RuntimeServices`; the virtual rig now drives
  the in-memory sequence adapter while the simulated runtime retains its small
  direct-color path for protocol lifecycle tests.
- `src/rpi_vstim/core/camera.py` and `src/rpi_vstim/camera/supervisor.py`
  intentionally serve fake and subprocess paths, but their lifecycle types
  overlap. Consolidate only after virtual-rig tests demonstrate the shared
  contract.
- `src/rpi_vstim/core/camera_identity.py` is an older compatibility module;
  `src/rpi_vstim/camera/identity.py` is the active stable resolver. Removing
  the old module would be a separate compatibility decision.
- Session artifacts have explicit versions and inspection rejects malformed or
  future versions for camera, resource, display, and durable metadata files.
- No production path silently falls back to `/tmp`, home storage, remote
  cameras, or hardware access in this audit baseline.

The remaining software-only work is heavy campaign execution, Linux CI/native
build verification, and independent review. Physical display/camera/SSD/GPIO/
photodiode acceptance remains deferred.
