# Manual bait and water-service operator controls

## Canonical behavior

`GPIO23` is the input-only `operator_bait_button`; `GPIO19` is the canonical
`reward_left`/`pump1` output. The button never electrically drives GPIO19.
`GPIO15` remains `lick_center`. `GPIO9` / PCB `DIO4` is reserved for future
IRIG output and is rejected by normal configuration and output ownership.

One manual bait request—from the button, terminal, or SSH—calls the same
calibrated `RewardController` operation:

```text
manual_bait_request -> one continuous calibrated GPIO19 opening
```

Manual bait is not a fake lick, trial, or task reward. Its source, target
volume, resolved open duration, calibration identity/hash, and reward events
are logged separately. The optional `max_manual_bait_water_ul` budget rejects
requests before GPIO19 is actuated; task and operator water counters remain
separate. `bait_auto_suction = false` is the default.

During an active session, startup composes one `RewardArbiter` and one
`RewardController` for both scheduled task rewards and manual bait. The
session-owned AF_UNIX endpoint and optional GPIO23 monitor only enqueue bounded
requests to that arbiter; they never create a second GPIO19 owner. A manual
request arriving while a task reward is active is rejected as busy.

Reward events are handed to a bounded background writer. Filesystem writes are
therefore outside the GPIO19 active interval. Final provenance records event
handoff drops/errors and a session is cleanup-failed if that writer cannot
flush/stop. If activation was attempted but delivery cleanup is uncertain,
water accounting conservatively retains the requested volume and logs an
uncertain/partial delivery.

`run_simulated_session()` calls `compose_session_reward_controls()` with the
simulated reward backend, keyboard enabled, and physical-button construction
disabled. Thus a production-like configuration may enable GPIO23 without
claiming it in simulation. The repository currently has no separate real
protocol session runner: `rpi-vstim run` still reports the Phase 00 placeholder.
When that runner is added, its session-start boundary must call the same helper
with the production `LgpioBackend` and physical-button construction enabled;
real in-session operator control is not claimed until that path exists.

## Normal baiting

Configure measured GPIO23 polarity before enabling the button:

```toml
[operator_controls]
manual_bait_enabled = true
bait_button_enabled = true
bait_button_gpio = 23
bait_button_idle_level = 0
bait_button_active_level = 1
bait_reward_ul = 3.0
minimum_interval_ms = 1000
bait_button_release_stable_ms = 25
bait_auto_suction = false
```

The polarity values above are an example, not a physical validation result.
The state machine emits one request per active contact, latches while held,
debounces release before re-arming, and does not use the 70 ms lick interval.

Set `bait_button_enabled = false` to leave GPIO23 unclaimed while retaining
terminal/SSH bait, provided `manual_bait_enabled` and calibrated reward
configuration are valid.

Start the local operator service:

```text
rpi-vstim operator service --config <rig.toml>
```

While an interactive terminal is attached, `B` or `b` requests one bait. The
same service exposes a restrictive local AF_UNIX endpoint for:

```text
ssh pi@10.42.84.10 rpi-vstim operator bait
```

The SSH command is only a local-socket client on the experiment Pi. There is no
unauthenticated network control listener, and `rpi_rig_monitor` remains
read-only.

## Plumbing prime and service

Prime is a raw maintenance opening, not a calibrated delivery:

```text
rpi-vstim water prime --config <rig.toml> --seconds N
```

`0 < N <= 300`; values above 300 seconds are rejected, not clamped. GPIO19
opens once, follows a monotonic deadline, and closes on completion, SIGINT,
SIGTERM, exception, or cleanup.

Physical hold-to-open is an explicit separate mode:

```text
rpi-vstim water service --config <rig.toml>
```

After GPIO23 is deliberately active, GPIO19 opens. GPIO23 release closes it.
Debounce prevents chatter, a held input is forcibly closed at 300 seconds, and
release is required before another opening. This mode and normal bait service
cannot run concurrently. The production `LgpioBackend` holds a kernel-backed
exclusive reward lock for GPIO19, so calibration and behavioral reward owners
are blocked too.

The service state remains open-or-unknown after a failed inactive write and
retries the inactive transition during cleanup; it does not report a normal
close until the baseline is confirmed. A single final idle edge is enough to
re-arm after the configured stable-release interval.

Service duration is never translated into uL. Only measured, rig-specific
collection calibration resolves target uL to a reward opening duration.

## Validation status

Software tests cover button latch/re-arm, keyboard/IPC convergence, source
logging, water accounting/limits, prime cleanup, hold timeout/release,
exclusive ownership, one-owner reward arbitration, nonblocking event logging,
calibration integrity checks, and GPIO9 rejection. The prototype has not physically
validated GPIO23 polarity or button behavior, and its reward plumbing is not
connected or water-calibrated. GPIO9 was not physically accessed.

## GPIO9 audit

| Occurrence class | Locations | Result |
|---|---|---|
| Canonical policy/runtime guard | `hardware/policy.py`, `core/config.py`, `hardware/lgpio_backend.py` | GPIO9 rejected; no IRIG backend implemented |
| Regression coverage | `tests/unit/test_lgpio_backend.py`, `tests/unit/test_operator_bait.py`, `tests/unit/test_operator_controls.py` | normal output, bait, and service paths fail closed |
| Current policy documentation | this report and `operator_bait_irig_policy_2026-10-03.md` | reservation recorded |
| Historical/reference material | `docs/hardware/pi5_gpio_reward_preflight_2026-09-26.md`, `docs/hardware/pi5_initial_audit.txt` | reference only; not runtime configuration |

No ordinary reward, bait, lick, vacuum, airpuff, trigger, camera, cue, or
water-service path assigns or acquires GPIO9. GPIO24 is the canonical
`trigger_out` mapping but is currently disabled and not acquired.
