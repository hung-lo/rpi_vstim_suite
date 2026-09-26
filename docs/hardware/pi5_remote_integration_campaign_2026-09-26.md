# Pi 5 remote integration campaign — 2026-09-26

Target: `pi@10.42.84.10`
Branch: `codex/pre-hardware-rc-hardening`
Validated source baseline: `8c1d3ef` plus the camera-command correction in
this change
Storage: experiment SSD absent; no SD-card production recording

This campaign used only short, bounded tests. It did not reboot the Pi, change
system configuration, touch GPIO, actuate reward/suction, manipulate lick or
photodiode hardware, contact an animal, or use the real monitor service.

## Executive conclusion

The Pi’s real HDMI-A-2 leased KMS path, stable dual-camera subprocess
supervisor, cleanup behavior, and bounded resource behavior passed the scoped
software/component campaign. The exact physical display output was not judged
visually.

The campaign also exposed and corrected the shared rpicam command builder to
use `--no-raw` and `--nopreview`; the initial failed camera attempt was caused
by the temporary harness passing the literal output path `unused`, not by the
camera hardware. Fifteen focused local supervisor tests pass after the fix.

The repository still does not contain a production unified real-camera session
runner, a real session-state writer for that runner, a network telemetry
publisher, or an implemented GPIO backend. Therefore the real failure,
SIGINT, and 20-session results below are explicitly component-composed
evidence, not acceptance of a unified animal-session runtime.

## A — clean Pi install and packaging

Pass in an isolated temporary Python 3.13.5 venv on the Pi:

- package installed locally with `pip install --no-deps .` and `PYTHONPATH`
  unset;
- `rpi-vstim` entry point resolved from the venv;
- imported package version and CLI `--version`: `0.1.0`;
- imported package came from venv site-packages, not the developer checkout;
- config validation passed for
  `config/rigs/pi5_dual_display_preflight.example.toml`;
- preflight and dry-run passed (asset library remained deferred because
  `/home/pi/stimulus_assets` is unavailable);
- all five simulations completed: natural-images, drifting-gratings,
  retinotopy, reward-conditioning, and spout-training;
- `inspect-session` passed for the generated natural-images simulation:
  `COMPLETE`, incomplete false, zero missing and zero corrupt artifacts.

The temporary venv was isolated from system Python. The Python package does
not embed the separately built native `kms_probe`; hardware use therefore
requires the explicit native binary path, which was supplied for the real
display tests. This is a packaging boundary, not a `PYTHONPATH` dependency.

The transfer checkout was a source archive and intentionally had no `.git`
directory; a final `git rev-parse` check against that archive was not a test
failure.

## B — production display protocol smoke

Pass for software/display-pipeline execution only. The test used the
production `KmsDisplayBackend` and `ProductionFrameRenderer` on HDMI-A-2,
connector 42, with leased ownership and synthetic/generated RGB frame pairs.
It ran for 10.877 seconds and planned/displayed exactly 420 frames:

| Sequence | Frames | Software check |
|---|---:|---|
| initial gray | 60 | gray preroll/finalization |
| synthetic natural A → B | 120 | distinct asset/frame identities |
| repeated A | 60 | repeated-image identity |
| synthetic B → C | 120 | transition identity |
| final gray | 60 | final gray |

All sequences reported exact requested/completed counts, contiguous kernel
sequences, alternating buffer ownership, no stale-frame reuse in the prepared
asset mapping, `restored=true`, and `ownership=lease-active`. The software
photodiode metadata convention was exercised, but no physical photodiode was
connected or measured. No claim is made about what the images looked like.

## C — real CameraSupervisor lifecycle

The first harness attempt failed at startup because its prebuilt command used
the literal output target `unused`; stderr showed the real camera reached
sensor configuration before libav rejected that target. Cleanup left no live
camera process, labwc remained alive, RAM was about 1.3 GiB available,
temperature was 37.3 °C, and throttling was `0x0`.

After correcting the harness output paths and the shared headless command
flags, six bounded cycles passed. Each cycle resolved both live stable
identities, started both cameras, captured for two seconds in
`/dev/shm/rpi_vstim_remote_test`, validated output growth and manifests, then
stopped/reaped both workers and deleted the cycle.

| Measurement | Result across six cycles |
|---|---:|
| cycles | 6/6 |
| startup time | 1.627–1.712 s |
| stop/reap time | 0.015–0.032 s |
| noir output growth | 245,760–270,336 bytes in sampled cycles |
| wide output growth | 212,992–237,568 bytes in sampled cycles |
| final manifest state | both `COMPLETED`, verification `recorded` |
| process residual | none |
| available RAM during capture | about 1.17–1.22 GiB |
| temperature | 38.4–41.7 °C |
| throttling | `0x0` throughout |

The workers ended with signal status `-15` after the supervisor’s requested
stop, while the supervisor classified the bounded stop as `COMPLETED` and
`recorded`. This is not SSD or production-storage acceptance.

## D — controlled camera failure

One actual failure injection passed at the component boundary:

- both real cameras started and produced bytes;
- one `imx708_noir` worker was deliberately terminated with SIGTERM;
- the supervisor observed required-camera state `FAILED`, exit `-15`, and the
  error `camera process exited during recording: -15`;
- the other camera remained active until normal supervisor cleanup and ended
  `COMPLETED`;
- a 60-frame HDMI-A-2 leased display operation completed and reported
  `restored=true`;
- display was closed, labwc remained alive, and no camera process remained.

There was no production real-camera session manifest to inspect. The harness
did not emit `COMPLETE` after the required camera failure; the absence of a
real unified session-state writer is a remaining software gap.

## E — SIGINT/interruption recovery

One corrected combined interruption test passed at the component boundary.
Both real cameras were recording, a 30-frame HDMI-A-2 leased display sequence
had completed, and the Python runtime was then interrupted with SIGINT. Its
state became `INTERRUPTED`; the `finally` path stopped both cameras, closed the
display boundary, and reported:

- both camera workers `COMPLETED` after requested stop, with signal status
  `-15`;
- no residual `rpicam-vid` or `kms_probe` process;
- labwc alive;
- display sequence `30/30`, `aborted=false`, kernel clock `monotonic`;
- available RAM about 1.23 GiB afterward, temperature 41.7 °C, throttling
  `0x0`.

The harness state was `INTERRUPTED`, but the temporary artifacts were removed
after inspection and the repository has no production real-camera session
artifact writer. “Partial session artifacts remain inspectable” is therefore
not claimed as a completed production-runtime check.

## F — repeated lease/release

Pass: ten iterations acquired only HDMI-A-2/connector 42, displayed 30 frames,
released, and checked recovery. Every iteration reported:

- `30/30`, `aborted=false`, `ownership=lease-active`, `restored=true`;
- `timing_source=kernel_event`, `kernel_timestamp_clock=monotonic`;
- HDMI-A-1/connector 33 still connected in the read-only inventory;
- labwc alive, zero camera/KMS residual processes, and `throttled=0x0`.

The native result and labwc continuity support compositor continuity. The
read-only connector inventory does not itself prove every compositor internal
state, so no stronger claim is made.

## G — telemetry

The existing bounded in-memory publisher passed on Pi Python 3.13.5:

- four schema-valid lifecycle/trial messages covered session state, trial
  completion, both camera states, required-camera failure/degraded state, and
  simulated reward/lick counters;
- a two-message bounded queue retained two and dropped two oldest messages;
- simulated receiver dropout (`fail_after=2`) returned `[true, true, false,
  false]` without blocking;
- no frame or pixel payload field entered telemetry.

A real loopback receiver was not run during this Pi campaign because that
checkout’s production `TelemetryPublisher` was explicitly a null publisher.
The monitor Pi was not contacted. Since the campaign, the branch has added a
hardware-independent AF_UNIX-to-UDP publisher and loopback demo/benchmark;
production session wiring, slow-receiver behavior on the Pi, and cumulative
network state remain unvalidated.

## H — short resource/leak campaign

Twenty composed real-display/two-camera sessions passed. Each used a fresh
RAM-backed session directory, displayed 30 frames on HDMI-A-2, recorded both
real cameras briefly, validated manifests, stopped/reaped workers, closed the
display, and deleted the session directory.

| Measurement | Result |
|---|---:|
| composed sessions | 20/20 |
| display | 30 completed frames per session; restored after each |
| camera manifests | both `COMPLETED`/`recorded` per session |
| session duration | 3.521–3.635 s |
| minimum after-session available RAM | about 1.28 GB |
| peak temperature | 44.4 °C |
| peak sampled load | 0.95 one-minute load average |
| throttling | `0x0` throughout |
| residual camera/KMS processes | none |
| labwc | alive throughout |

This is a composed component campaign, not a claim that the absent unified
real-session runner is complete. No SSD or SD-card production recording was
performed.

## I — GPIO/reward audit

The read-only source findings and Monday checklist are in
`docs/hardware/pi5_gpio_reward_preflight_2026-09-26.md`. The current unified
defaults and legacy frozen profile disagree in scope (single reward/lick
defaults versus multi-channel legacy mappings), and source does not establish
electrical polarity for the actual harness. No GPIO state was changed.

## Remaining Monday checks

1. Physically map the harness and confirm the profile: reward outputs,
   suction/vacuum, lick channels, trigger/TTL lines, and reserved pin 9.
2. Confirm common ground, 3.3 V compatibility, pull-up/down requirements,
   active electrical levels, edge semantics, and driver safe states.
3. Verify reward/suction isolation and measured fluid delivery/calibration with
   no animal connected.
4. Implement and test the real `lgpio` backend only after the map is signed
   off, including startup-safe, shutdown-safe, and SIGINT cleanup behavior.
5. When the SSD is present, resolve its identity/mount and perform storage
   acceptance before any production recording claim.
6. Wire the local UDP telemetry boundary into the real session runner and
   validate it against the monitor receiver.
7. Integrate the real camera supervisor and display backend into one session
   state writer that persists `COMPLETE`, `FAILED`, `INTERRUPTED`, and partial
   artifacts correctly.
8. Perform physical photodiode timing and optical/image acceptance with the
   final screen and acquisition hardware.
