# Operator bait button and GPIO9 IRIG reservation

## Canonical policy

The lab-wide BehavBox map is:

| Role | BCM GPIO | Policy |
|---|---:|---|
| `lick_left` | 26 | input |
| `lick_right` | 27 | input |
| `lick_center` | 15 | reserved for future center lick input |
| `reward_left` | 19 | calibrated output |
| `reward_right` | 20 | canonical actuator mapping |
| `reward_center` | 21 | canonical actuator mapping |
| `reward_4` | 7 | canonical actuator mapping |
| `airpuff` | 8 | canonical actuator mapping |
| `vacuum` | 25 | canonical actuator mapping |
| `operator_bait_button` | 23 | input-only operator control |
| `trigger_out` | 24 | canonical, currently disabled/not implemented |
| `irig_output` | 9 | reserved exclusively for future IRIG |

This change does not implement IRIG generation. GPIO9 / PCB `DIO4` is not
available to normal behavior or control code. GPIO24 is not acquired by this
repository, but it is not part of the permanent IRIG reservation.

The runtime policy error is deliberately explicit: `BCM GPIO9 is reserved for
IRIG output.` The current source/configuration occurrences of GPIO9, DIO4, and
IRIG are policy guards, tests, and hardware-validation/reference
documentation. No ordinary experiment, operator-control, water-service, or
calibration path acquires GPIO9.

## Operator bait behavior

The conditioned button input is configured with explicit `idle_level` and
`active_level`; the software never assumes its polarity. GPIO23 is monitored
for both edges. The state machine emits one `ManualBaitRequest` on a valid
active transition, latches while active, and only re-arms after the inactive
level has remained stable for `bait_button_release_stable_ms`.

The default `manual_bait_min_interval_ms` is 1000 ms. This is intentionally
separate from the 70 ms lick classifier interval. A held button, switch bounce,
or rapid repeated tap cannot generate repeated requests.

Requests are passed to `ManualBaitService`, which calls the existing
`RewardController`. The controller remains the sole mechanism allowed to
deliver reward GPIO19 intervals. Manual bait therefore uses the configured
calibrated reward profile and emits the same reward event sequence.

`manual_bait_enabled` is the global capability switch. Terminal/SSH bait does
not require the physical button; GPIO23 is claimed only when
`bait_button_enabled = true`, and that mode additionally requires explicit
polarity. During an active experiment, the session owns GPIO19 once and task
rewards plus manual bait are serialized by one `RewardArbiter`. A manual bait
that arrives while a task reward is open is rejected with a logged busy reason;
it is never overlapped or handed to a second GPIO backend.

Example configuration:

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
# Optional cumulative operator-bait water budget:
# max_manual_bait_water_ul = 300.0
```

The example polarity is illustrative only. It must be replaced by the result
of physical idle/active, bounce, and press/release characterization.

## Hardware status

This commit adds the software policy and deterministic tests. It does not
claim physical GPIO23 validation, reward delivery acceptance, water-volume
calibration, or IRIG validation.

## Operator-control processes

All manual sources converge on `manual_bait_request` and then the existing
`RewardController`; no source writes GPIO19 directly:

```text
GPIO23 press ─┐
terminal B ───┼─> manual_bait_request -> RewardController -> one calibrated GPIO19 opening
SSH operator bait ┘
```

Run the standalone service on an idle rig with `rpi-vstim operator service`. It
owns a restrictive AF_UNIX socket configured by `paths.operator_control_socket`.
For a behavioral session, construct the same service against that session's
arbiter; the standalone service cannot acquire GPIO19 while the session owns
it.
The remote command is:

```text
ssh pi@<rig> rpi-vstim operator bait
```

The handoff is bounded and acknowledged; the socket is local to the rig and is
not a network reward server. A terminal `B`/`b` request is nonblocking and the
configured one-second operator interval, button latch, and optional cumulative
`max_manual_bait_water_ul` cap prevent accidental bursts. Operator bait water
is logged separately from task reward water. Events use a bounded nonblocking
handoff and a background writer, so filesystem I/O is outside the valve-open
interval. `bait_auto_suction` is explicit
and defaults to false.

## Water service / prime

Water service is not a behavioral reward and is never converted into volume:

```text
rpi-vstim water prime --config <rig.toml> --seconds N
rpi-vstim water service --config <rig.toml>
```

`N` must be greater than zero and no greater than the central hard limit of
300 seconds. Prime opens GPIO19 once until its monotonic deadline. Service
mode uses GPIO23 hold-to-open, closes on release, forces closure at 300
seconds, and requires release before another opening. SIGINT, SIGTERM,
exceptions, and normal exit close the line. Both modes use the production
`LgpioBackend` and its exclusive kernel-held reward lock; behavioral reward
sessions, manual-bait service, calibration, and water service cannot
independently own GPIO19 at the same time.

The current prototype has no connected reward plumbing and no validated GPIO23
button polarity. Therefore no water volume, service-button behavior, or final
actuator acceptance is claimed. Actual calibration remains rig-specific and
must use measured collection mass with the existing continuous-open calibration
tool.
