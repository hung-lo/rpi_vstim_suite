# Overnight software groundwork report

Date: 2026-09-24
Branch: `codex/overnight-software-groundwork`

## Completed

- Simulated session lifecycle with deterministic seeds, manifests, event logs,
  provenance, plans, interruption/failure handling, and safe cleanup.
- Deterministic frame/event plans with phase, trial/sequence IDs, photodiode
  intent, frame offsets, and stable JSON serialization.
- Natural-image discovery, deterministic subset/repetition scheduling, integer
  frame ITIs, and explicit `natural_legacy_plain` and
  `natural_legacy_camera` profiles.
- Hardware-free reward conditioning with persistent assignment helper,
  acquisition/reversal state, frozen 50-trial 8:3:1 blocks, water limits, and
  the 500-trial production schedule of 198 rewards and 22 omissions.
- Versioned protocol-neutral telemetry messages and bounded in-memory/null
  publishers.
- Independent metadata-only fake supervision for two local cameras, including
  required/optional failure and degraded states. No device nodes or frame data
  are accessed.
- CLI simulation paths, configuration examples, session-format docs, camera
  workflow docs, reward-timing docs, and acceptance tests.

## Milestone commits

| Milestone | Commit |
| --- | --- |
| A — simulated runtime | `20acaa4` |
| B — deterministic planning | `9ed5f24` |
| C — natural-image planning | `cf266d5` |
| D — reward-conditioning logic | `c706a74` |
| E — telemetry contract | `fe5d39d` |
| F — fake local cameras | `7baec0f` |
| C/D source-alignment correction | `bae2f4b` |
| G — simulated acceptance groundwork | `2f62895` |
| final planner/status correction | `3831203` |

The required final report commit is the commit containing this file.

## Validation

- `python -m pytest -q`: **55 passed in 0.24s**.
- `python -m compileall -q src tests`: passed.
- `bash -n scripts/*.sh`: passed.
- `git diff --check`: passed.
- Ruff: **unavailable** in the active environment; not claimed as passed.
- CLI smoke with `PYTHONPATH=src python -m rpi_vstim`: version, protocol list,
  config validation, natural simulation, and reward simulation all passed.
- Experimental validation regression rejected the non-experimental example with
  exit code **2**, as required.
- Acceptance tests cover no-camera natural simulation, two fake local cameras,
  reward scheduling, interruption, protocol/camera/telemetry failure,
  degradation, deterministic replay, bounded telemetry, output manifests, and
  cleanup safety.

## Scope and deferrals

- Phase 01 was not started.
- `main` was not changed and commit `2a17339` was not squashed.
- No Pi access, real display/KMS, GPIO, camera capture, reward delivery,
  suction, lick capture, UDP telemetry, SSH camera control, cross-Pi transfer,
  or system-service changes were performed.
- The reusable Pi audit script is updated in the inherited Phase 00 history,
  but the expanded audit was not rerun because the Pi is unavailable from this
  Mac. That is deferred hardware validation, not a software failure.
- The four reference repositories were read-only inputs. Their existing
  untracked patch files were preserved and not edited.

## Reference baselines read

- `rpi_rig_monitor`: `70b80f25c12ac64d087ebeb78a22a091a0d03511`
- `rpi_visual_stimuli`: `6e1b2776e59c89127f9a6b56854096eb726990da`
- `vstim_natural`: `8a5f368c20344e25500cdfa6b272eccb673cad4a`
- `vstim_natural_img_reward`: `f64b56d0562b5c35aa64ffba34c29b1d7416bec1`

Known user-provided untracked files in this checkout—
`OVERNIGHT_SOFTWARE_GROUNDWORK_CODEX_DESKTOP.md` and
`phase00_cleanup_98b9006.patch`—were preserved untouched.
