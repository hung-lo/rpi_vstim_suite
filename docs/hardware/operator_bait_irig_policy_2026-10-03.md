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
| reserved output | 24 | unused |
| `irig_output` | 9 | reserved exclusively for future IRIG |

This change does not implement IRIG generation. GPIO9 / PCB `DIO4` is not
available to normal behavior or control code, and GPIO24 is also rejected as a
reserved unused output.

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

Example configuration:

```toml
[operator_controls]
bait_button_enabled = true
bait_button_gpio = 23
bait_button_idle_level = 0
bait_button_active_level = 1
bait_reward_ul = 3.0
minimum_interval_ms = 1000
bait_button_release_stable_ms = 25
```

The example polarity is illustrative only. It must be replaced by the result
of physical idle/active, bounce, and press/release characterization.

## Hardware status

This commit adds the software policy and deterministic tests. It does not
claim physical GPIO23 validation, reward delivery acceptance, water-volume
calibration, or IRIG validation.
