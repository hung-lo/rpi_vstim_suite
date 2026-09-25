# Phase 00 review fixes for `rpi_vstim_suite`

Review target: commit `2a17339` (`codex/phase-00-bootstrap`)

Do **not** start Phase 01 in this task. Keep the Phase 00 architecture and scope. Make only the focused corrections below, add tests, run the Phase 00 test suite, and commit the fixes on the current branch.

## 1. Fix experimental config validation semantics

Current problem:

- `rpi-vstim config validate --experimental` passes `require_paths=True`, but it does not require `[session] experimental=true` and does not force the experimental safety rules to apply.
- A config with `display.backend="fake"`, `hardware.backend="simulated"`, `session.experimental=false`, and `session.simulation=true` can therefore be reported as valid by `--experimental` if its paths exist.
- `config_from_mapping()` also calls `Config.validate()` immediately, which couples pure config parsing to host filesystem availability when `session.experimental=true`. This makes it difficult to inspect an experimental config on a development machine that does not have the Pi mounts.

Required behavior:

- Separate structural/safety validation from host/environment path validation.
- Loading/parsing a config must not require the Pi filesystem to exist.
- `Config.validate()` should still enforce internal safety combinations, including experimental mode not using simulation/fake hardware.
- Path/device/environment checks should run only when explicitly requested by a preflight/CLI hardware validation step.
- `rpi-vstim config validate --experimental` must reject a config unless it is genuinely configured for experimental operation (`session.experimental=true`, `session.simulation=false`) and all experimental safety constraints pass.

Suggested minimal implementation:

- Make `require_paths=False` the default for pure config validation, or otherwise ensure `config_from_mapping()` performs only non-environment validation.
- In the CLI, when `--experimental` is requested, explicitly require `config.session.experimental is True` and then run `config.validate(require_paths=True, repo_root=...)`.
- Keep normal `config validate` usable on a laptop without `/mnt/hd`.

Add tests proving:

1. fake display + simulated GPIO + `session.experimental=false` is rejected by `config validate --experimental` even when all paths exist;
2. parsing an experimental config on a machine without Pi mounts can still perform structural validation without touching the filesystem;
3. explicit experimental/preflight validation does check required paths.

## 2. Validate hardware/telemetry configuration values

Current problem:

- `HardwareConfig.backend` is not validated against supported values.
- Any arbitrary string other than `"simulated"` can satisfy the current experimental-mode check.
- `hardware.chip` is not range/validity checked.
- `telemetry.required=true` with `telemetry.enabled=false` is currently accepted.

Required changes:

- Accept only currently supported hardware backend names, at minimum:
  - `simulated`
  - `lgpio`
- Reject unknown backend names.
- Require `hardware.chip >= 0`.
- If `telemetry.required=true`, require `telemetry.enabled=true`.
- Keep telemetry host/port validation already present.

Add unit tests for all of the above.

Do not add new GPIO libraries in this Phase 00 fix.

## 3. Make persisted session metadata actually reproducible

Current problem:

`SessionContext` contains `random_seeds` and `source_commit`, but `write_initial_outputs()` never writes those fields. A session created with a non-default seed therefore loses that seed from the persisted metadata.

Required changes:

- Persist the protocol/random seed information in `session_manifest.json` or another clearly documented common metadata file.
- Persist the resolved source commit in the session metadata.
- Avoid storing two independently-derived source commit values that could disagree. Collect/resolve provenance once per session and use the same value consistently.
- Keep the existing `resolved_config.json` and `provenance.json` outputs.

Add a test that creates a session with a known seed and `RPI_VSTIM_SOURCE_COMMIT` value and verifies both survive in the written metadata.

## 4. Correct lifecycle terminal-state handling

Current problem:

`Lifecycle.transition()` blocks transitions only from `COMPLETE`, `FAILED`, and `CLEANUP_FAILED`. It currently allows transitions such as:

- `INTERRUPTED -> TASK`
- `INCOMPLETE -> TASK`

Those states should be terminal for an experimental session.

Required minimal change:

Treat at least these states as terminal:

- `COMPLETE`
- `INCOMPLETE`
- `INTERRUPTED`
- `FAILED`
- `CLEANUP_FAILED`

Do not build a large transition-state framework yet unless necessary. A small terminal-state constant/set is sufficient for Phase 00.

Add tests confirming terminal states cannot transition again.

## 5. Strengthen fake display validation

Current problem:

`FakeDisplayBackend.validate_program()` checks width, height, and pixel format, but does not check refresh rate. A 59 Hz frame program is accepted by a display configured for 60 Hz, which weakens future laptop-side golden/timing tests.

Required change:

- Validate that `FrameProgram.refresh_hz` matches the opened `DisplayConfig.refresh_hz` using a small explicit floating-point tolerance.
- Keep the fake backend deterministic and non-sleeping.

Add a test confirming a refresh mismatch is rejected.

## 6. Make experimental path checks role-aware

Current problem:

When path validation is enabled, every path is required to be writable, including `asset_root`. Stimulus assets may reasonably be mounted read-only.

Required behavior:

- `output_root`: must exist and be writable for experimental preflight.
- `cache_root`: must exist and be writable.
- `reward_state_root`: must exist and be writable.
- `asset_root`: must exist and be readable; do not require write access.
- Keep the safety rule that `reward_state_root` must not live inside the code checkout.

Add a focused unit test if practical without relying on root-only permission semantics. If Unix permission behavior makes such a test unreliable in CI, isolate the access-check helper and unit test the role selection separately.

## 7. Bring the reusable Pi audit script up to the recorded audit level

Current problem:

`docs/hardware/pi5_initial_audit.txt` contains useful information beyond what `scripts/audit_pi5.sh` currently collects. The script should be able to reproduce the important hardware inventory on the next lab run.

Update the read-only audit script to collect, where available and without modifying the Pi:

- hostname / identity / groups
- model and OS
- Python version and executable
- kernel / architecture
- RAM and filesystem/mount status
- `which pip3`, `which ffmpeg`
- DRM cards, connectors, connector status, and available modes
- framebuffer compatibility nodes
- GPIO chips / `gpioinfo`
- video devices
- time sync status
- network interface summary
- relevant loaded DRM modules (`vc4`, `drm`)
- display/session variables when meaningful (`XDG_SESSION_TYPE`, `WAYLAND_DISPLAY`, `DISPLAY`)

Keep it strictly read-only.

The laptop currently may not have SSH access to `pi@10.42.84.10`. Do not treat inability to rerun the audit from the laptop as a software blocker. Update the script now and document that the expanded audit should be rerun on the lab network before the first Pi hardware phase.

Do not store secrets, SSH keys, passwords, or tokens.

## 8. Fix misleading documentation wording

The README and CLI module currently call the Phase 00 code "non-hardware-safe" even though the intended property is that imports/diagnostics do not access real hardware.

Change this wording to something unambiguous such as:

- "hardware-safe Phase 00 skeleton"
- or "non-hardware Phase 00 command-line surface"

Do not imply that Phase 00 is unsafe for hardware.

## Keep these existing decisions

Do not change these in this fix:

- Python target remains `>=3.13,<3.14`.
- `rpi_rig_monitor` remains a separate repository.
- No real UDP sends yet.
- No real GPIO access yet.
- No camera acquisition yet.
- No DRM/KMS implementation yet.
- No reward delivery or protocol scheduling yet.
- Keep the physical OL7 geometry metadata currently recorded (`15.50 x 8.72 cm`, `16.0 cm` eye distance) as provisional until hardware display calibration.
- Keep the old repositories as reference implementations only; do not alter or merge them.

## Tests / checks before committing

Run, at minimum:

```bash
python -m pytest -q
python -m compileall -q src tests
```

If Ruff is available in the active environment, also run:

```bash
ruff check .
```

If Ruff is not installed, report that clearly rather than claiming it passed.

Also manually verify:

```bash
rpi-vstim --version
rpi-vstim list-protocols
rpi-vstim config validate config/system.example.toml
```

For the experimental CLI regression, create a temporary config whose paths all exist but whose session remains simulation/fake; verify:

```bash
rpi-vstim config validate TEMP_CONFIG.toml --experimental
```

returns non-zero.

## Final report

Report:

1. exact files changed;
2. tests added;
3. exact pytest result;
4. Ruff result or explicit unavailable status;
5. whether the expanded Pi audit was rerun or deferred because the Pi is unreachable;
6. commit hash.

Commit the fix on `codex/phase-00-bootstrap` with a message similar to:

`Harden Phase 00 validation and reproducibility`

Stop after this Phase 00 review fix. Do not start Phase 01.
