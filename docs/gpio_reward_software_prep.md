# GPIO/reward software preparation

The desktop test suite does not access GPIO. The simulated hardware worker
keeps reward, suction, lick, and optional TTL outputs safe, and the
configuration validator rejects conflicting BCM pin assignments.

The Pi 5 output boundary now has a native `lgpio` backend for the configured
`reward` and `vacuum` semantic roles. It claims only the requested roles,
applies an explicit electrical initial level at claim time, records monotonic
transition timestamps and optional readback, supports bounded electrical
pulses, and releases every claim on normal exit or interruption. Protocols use
semantic roles and configuration; they do not contain BCM numbers.

The broader hardware worker boundary remains separate: camera and display
workers must not own GPIO or run reward logic. Reward/water-limit state,
lick-edge events, and full production orchestration remain bounded worker
contracts rather than assumptions in this line-control backend.

The prototype configuration maps BCM19 to the candidate reward role and BCM25
to the candidate vacuum role, with both electrical initial levels set to LOW.
Active polarity is intentionally unset: electrical HIGH/LOW is not called
actuator ON/OFF. GPIO19 and GPIO25 line control can be validated with the
unconnected LED-style indicators, but reward delivery, suction actuation,
polarity, water limits, and final-rig acceptance remain deferred. GPIO7,
GPIO8, GPIO20, GPIO21, cue LEDs, and trigger outputs are outside this backend
and must not be touched by this validation.
