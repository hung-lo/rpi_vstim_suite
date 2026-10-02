# Pi 5 GPIO/reward preflight — 2026-09-26

This is a read-only source audit for Monday’s hardware bring-up. No GPIO was
exported, claimed, toggled, or electrically probed during the audit. The
following is source evidence, not confirmation that the harness is wired this
way.

## Canonical lab BehavBox mapping — 2026-09-30

The lab uses one canonical BehavBox BCM map across rigs:

| BCM GPIO | Function mapping | Function-mapping status | Polarity status |
|---:|---|---|---|
| 19 | reward_left / pump1 | Canonical lab map | Not physically validated |
| 25 | vacuum / pump_en | Canonical lab map | Not physically validated |
| 7 | unresolved / legacy `reward_4` role | Not separately tested | Not evaluated |
| 8 | unresolved / legacy airpuff role | Not separately tested | Not evaluated |

GPIO7 briefly drove the vacuum only because the vacuum line was temporarily
rewired there during testing. That temporary wiring was moved back to GPIO25;
GPIO7 is not the production vacuum mapping. GPIO8 remains unresolved until it
is separately tested. Function mapping and electrical polarity are independent
validation fields; no active-high or active-low behavior is inferred here.

## Current unified checkout

The current configuration model defines these software defaults in
`src/rpi_vstim/core/config.py`:

| Function | BCM pin in current model | Evidence/status |
|---|---:|---|
| reward | 19 | `HardwareConfig.reward_pin_bcm`; software default only |
| suction | 25 | `HardwareConfig.suction_pin_bcm`; software default only |
| lick | 26 | `HardwareConfig.lick_pin_bcm`; software default only |
| TTL | unset | `HardwareConfig.ttl_pin_bcm = None` |

The Pi 5 fixture now defines `[hardware]` for the two canonical output lines
and uses the native `LgpioBackend` for the dedicated line validator.
`RewardController`, `SuctionController`, `LickInput`, and `TtlOutput` remain
broader protocol/worker placeholders, while ordinary desktop/runtime tests
continue to use the simulated hardware boundary. The final rig must be
verified as physically wired to this canonical map; the BCM assignments are
not awaiting a new breakout-map decision.

## Frozen/reference repository evidence

Read-only inspection of `/home/pi/RPi4_behavior_boxes_hardware` found the fixed
profile manifest in `box_runtime/io_manifest.py`. It is the clearest source
for legacy semantic names and BCM numbers:

| Semantic role | BCM pin | Board/legacy label | Source notes |
|---|---:|---|---|
| reward left | 19 | `pump1` | `head_fixed` and `freely_moving` |
| reward right | 20 | `pump2` | `head_fixed` and `freely_moving` |
| reward center | 21 | `pump3` | `head_fixed` and `freely_moving` |
| reward 4 | 7 | `pump4` | `head_fixed` and `freely_moving` |
| reward 5 / airpuff | 8 | `pump5` | profile-dependent name |
| suction/vacuum | 25 | `pump_en` | both profiles |
| lick left | 26 | `Lick1` | `head_fixed` |
| lick right | 27 | `Lick2` | `head_fixed` |
| lick center | 15 | `Lick3` | `head_fixed` |
| trigger input | 23 | `DIO1` | input |
| trigger output | 24 | `DIO2` | output |
| user-configurable output | 4 | `Camera` | not a reward/suction line |
| reserved IRIG output | 9 | `DIO3` | explicitly reserved; not BehavBox-owned |

The older `/home/pi/RPi4_behavior_boxes/essential/behavbox.py` independently
constructs reward outputs on 19, 20, 21, 7, 8, and 25, and lick inputs on 26,
27, and 15. It also contains historical conflicting reuse/comments around
pins 23/24 and pin 9. The newer frozen manifest is profile-aware, but the
legacy agreement is not enough to establish the physical harness assignment.

## API, polarity, timing, and cleanup evidence

- The reference runtime uses `gpiozero` (`LED`, `PWMLED`, `DigitalOutputDevice`,
  and `Button`), not `lgpio` directly.
- Outputs are driven with `.on()`, `.off()`, and `.blink()`. The source does
  not set an explicit `active_high` value for the output devices.
- Frozen input setup uses `Button(pin, pull_up=None, active_state=True)`. The
  older IR input comments explicitly describe `Button(..., None, True)` as
  inverting the signal so `poke=True` and `no-poke=False`; the electrical
  sensor polarity and lick wiring are not documented well enough to generalize
  that statement to the harness.
- `OutputService.pulse_output()` uses the requested duration and a 0.1 s
  off-time for blink-capable outputs. Reward duration is calculated from the
  stored linear calibration and rounded to five decimal places. Default
  vacuum/airpuff duration is 0.01 s when no duration is supplied. These are
  software timings, not measured valve/pump timings.
- `InputService` samples the treadmill at a configurable rate, default 30 Hz;
  this is unrelated to lick electrical timing.
- `InputService.close()` stops the sampler, joins it for up to one second, and
  closes input devices. `OutputService.close()` closes each output and
  tolerates a known GPIO-busy teardown race. `BehavBox.close()` closes inputs,
  outputs, recording, sound, and camera resources. The current unified
  checkout has no implemented GPIO cleanup path to validate on the Pi.
- The reference mock maps output `.on()` to logical `1` and `.off()` to
  logical `0`; that mock behavior is not electrical evidence.

## Monday bring-up checklist

1. With loads isolated and no software output claim, identify the actual box
   harness and record each actuator/sensor wire against the BCM/header pin.
2. Resolve the profile choice: confirm whether the box exposes one reward line
   (current unified default 19) or the legacy multi-output map (19/20/21/7/8),
   and distinguish suction/vacuum 25 from any pump-enable convention.
3. Identify the actual lick sensor count and map it to 26/27/15 or another
   documented pin. Confirm common ground, 3.3 V compatibility, pull-up/down
   requirements, and the sensor’s asserted electrical level.
4. Identify trigger/TTL input and output lines (legacy DIO1/23 and DIO2/24),
   their voltage levels, edge meaning, and whether pin 9 is still reserved for
   IRIG. Do not assume a TTL name means a particular polarity.
5. Verify reward and suction driver isolation, flyback/protection, valve/pump
   polarity, and safe power-off state with the hardware owner. Confirm that no
   load actuates when the Pi pin is released.
6. Confirm reward volume calibration and pulse timing with the fluid path
   disconnected from an animal. Record measured delivery and required minimum
   on/off times; do not reuse legacy coefficients without evidence.
7. Only after the physical map is signed off, implement and test the `lgpio`
   backend with explicit safe-low/high-Z behavior, startup safe state,
   interruption cleanup, and a read-only/input-only verification mode.

Until those checks are complete, reward, suction, lick, TTL, active-high, and
active-low behavior remain unvalidated. No undocumented wiring is inferred by
this report.

## Prototype GPIO output-line validation — 2026-10-02

The prototype validation scope is intentionally limited to the two unconnected
indicator lines:

| BCM GPIO | Electrical output control | Canonical role | Real circuit | Polarity | Final rig |
|---:|---|---|---|---|---|
| 19 | Physically validated on prototype | reward_left / pump1 | Not connected | Not validated | Verify canonical wiring and actuator |
| 25 | Physically validated on prototype | vacuum / pump_en | Not connected | Not validated | Verify canonical wiring and actuator |

The production-compatible Pi 5 backend uses native `lgpio`, resolves these
lines from `[hardware]` configuration, claims only the requested semantic
role, starts at the configured electrical level, records monotonic transition
timestamps/readback when available, and releases ownership on normal,
exception, or SIGINT cleanup. `reward_active_level` and
`suction_active_level` remain unset; HIGH and LOW therefore mean only
electrical levels, never actuator ON/OFF.

The real prototype line checks are run independently with
`scripts/validate_gpio_output.py`: one role per process, no simultaneous
toggle, three one-second HIGH/LOW cycles, and 50 ms pulses in both electrical
directions. They are output-line checks only. No reward pump or vacuum circuit
was connected or actuated, and this evidence must not be promoted to final-rig
reward/vacuum acceptance. The BCM mapping is canonical; the connected driver
board's active polarity and actuator behavior remain to be validated.

### 2026-10-02 Pi results

The checks ran on the prototype Pi 5 using the native `lgpio` backend and
`config/rigs/pi5_dual_display_provisional.example.toml`:

- GPIO19 / `reward`: three visually confirmed blinks; every HIGH/LOW readback
  matched; final electrical LOW; clean release; no warnings.
- GPIO25 / `vacuum`: three visually confirmed blinks; every HIGH/LOW readback
  matched; final electrical LOW; clean release; no warnings.
- Both lines independently produced LOW→HIGH and HIGH→LOW 50 ms pulses. The
  measured userspace intervals were approximately 50.07–50.08 ms; this is not
  a microsecond-precision timing claim.
- Normal start/stop, intentional exception cleanup, and SIGINT cleanup passed
  independently for both lines. Each interruption reported `release_success`.
- A fresh process reacquired each line after cleanup, confirming no lingering
  GPIO consumer.

The first attempted claim exposed that this Pi's `lgpio` build implements the
four-argument `gpio_claim_output(handle, flags, gpio, level)` form; the
backend was corrected before any line cycle ran. No other BCM GPIO was
acquired, toggled, or tested.
