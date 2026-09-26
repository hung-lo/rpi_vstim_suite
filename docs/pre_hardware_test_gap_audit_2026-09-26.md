# Pre-hardware test-gap audit

Baseline: `codex/pre-hardware-rc-hardening` at parent `15cd7ab`. Local
`coverage`/`pytest-cov` is unavailable, so this audit uses the test inventory,
targeted branch inspection, and standalone campaigns. The fast suite grew from
195 baseline tests to 201 after the RC changes.

## Closed high-value gaps

| Area | Closure | Validation |
|---|---|---|
| EOF, timeout, abort, backpressure | Existing transport tests plus randomized campaign | `tests/unit/test_display_sequence.py`, state campaign |
| Camera partial startup, stall, kill/reap | Real subprocess emulator and supervisor fixtures | `tests/unit/test_camera_subprocess.py`, virtual rig |
| Storage permission/space/fsync/collision/path replacement | Fault-injected preflight/session tests | `tests/unit/test_storage_preflight.py` |
| Session corruption/future schema/orphan output | Versioned reader and inspection tests | `tests/unit/test_session_inspection.py` |
| Required/optional camera divergence | Required failure integration and optional policy tests | camera supervisor and virtual-rig tests |
| Deterministic plans/assets | Paired campaign and all-five protocol goldens | `scripts/reproducibility_campaign.py` |
| Telemetry backpressure | Bounded publisher stress and envelope contract tests | `scripts/stress_telemetry.py` |
| Resource/lifecycle cleanup | Leak snapshots and repeated lifecycle campaigns | `scripts/leak_campaign.py`, `scripts/soak_virtual_sessions.py` |

## Intentional remaining gaps

- Branch coverage percentages are not claimed without the unavailable coverage
  tool.
- Hard-kill power-loss behavior is represented by inspectable interruption and
  fault campaigns; actual power loss and filesystem recovery remain Pi/SSD
  validation.
- Native Linux headers and libraries are unavailable on this Mac. The
  reproducible CI workflow and build script are the software closure.
- Physical KMS page flips, camera topology, SSD identity/throughput, GPIO,
  reward, lick, and photodiode checks remain hardware-gated.

No gap closure changes historical hardware reports or frozen repositories.
