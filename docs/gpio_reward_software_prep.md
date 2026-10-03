# GPIO/reward software preparation

The desktop test suite does not access GPIO. The simulated hardware worker
keeps reward, suction, lick, and optional TTL outputs safe, and the
configuration validator rejects conflicting BCM pin assignments.

The Pi 5 output boundary now has a native `lgpio` backend for the configured
`reward_left` and `vacuum` semantic roles. It claims only the requested roles,
applies an explicit electrical initial level at claim time, records monotonic
transition timestamps and optional readback, and releases every claim on
normal exit or interruption. Protocols use semantic roles and configuration;
they do not contain BCM numbers.

Reward delivery is implemented by `RewardController` as one continuous
`active_level` interval, using a monotonic deadline and then the configured
inactive level. It does not use six-pulse fields or the generic electrical
test-pulse helper. The event sink records `reward_command`,
`reward_valve_on`, `reward_valve_off`, and `reward_complete`.

The broader hardware worker boundary remains separate: camera and display
workers must not own GPIO or run reward logic. Reward/water-limit state,
lick-edge events, and full production orchestration remain bounded worker
contracts rather than assumptions in this line-control backend.

The operator bait input is an input-only GPIO23 (`operator_bait_button`). It
creates a software request; it never electrically drives GPIO19. The request
must be handled by `ManualBaitService` and the existing `RewardController`,
so manual baiting uses the same calibration, polarity, timing, cleanup, event,
and provenance path as task rewards. GPIO15 remains `lick_center` and is not
used for baiting. GPIO24 remains reserved/unused.

GPIO9 / DIO4 is reserved exclusively for a future `irig_output`. IRIG
generation is not implemented here, and normal output backends reject both
GPIO9 and the reserved GPIO24 rather than claiming them.

The prototype configuration preserves the canonical lab BehavBox map: BCM19
is `reward_left`/`pump1`, and BCM25 is `vacuum`/`pump_en`; both electrical
initial levels are LOW. The eventual rig must be verified against that
canonical wiring. Active polarity is intentionally unset: electrical HIGH/LOW
is not called actuator ON/OFF. Water-volume calibration and safe
startup/shutdown with the connected driver board remain deferred until the
real reward circuit is attached. GPIO7, GPIO8, GPIO20, GPIO21, cue LEDs, and trigger outputs are
outside this backend and must not be touched by this validation.
