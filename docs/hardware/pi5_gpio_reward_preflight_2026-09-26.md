# Pi 5 GPIO/reward preflight — 2026-09-26

This is a read-only source audit for Monday’s hardware bring-up. No GPIO was
exported, claimed, toggled, or electrically probed during the audit. The
following is source evidence, not confirmation that the harness is wired this
way.

## Current physical mapping correction — 2026-09-30

The current rig mapping supplied by the hardware owner is:

| BCM GPIO | Function mapping | Function-mapping status | Polarity status |
|---:|---|---|---|
| 19 | reward pump | Current physical mapping confirmed | Not physically validated |
| 25 | vacuum | Current physical mapping confirmed | Not physically validated |
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

The Pi preflight display/camera fixture does not define `[hardware]`, so it
inherits those defaults. Its backend remains non-actuating: the current
`LgpioBackend`, `RewardController`, `SuctionController`, `LickInput`, and
`TtlOutput` are placeholders, while the exercised runtime used the simulated
hardware boundary. No current unified GPIO mapping should be treated as an
authoritative harness map.

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
