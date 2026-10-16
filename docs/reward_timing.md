# Reward timing

Overnight groundwork contains hardware-free reward planning only: permanent
14-image assignment groups, explicit acquisition/reversal state, 50-trial
8:3:1 blocks, and the frozen 10-block production schedule of 220 eligible
cues, 198 scheduled rewards, and 22 scheduled omissions. It does not actuate
water, suction, or lick hardware. The legacy Box151 calibration is reference
only and is not a Pi 5 default.

## Unified delivery semantics

The legacy `vstim_natural_img_reward` implementation treated one behavioral
reward as six valve pulses, with an off gap between pulses. The unified Pi 5
semantics intentionally differ: one reward is exactly one continuous active
interval on `reward_left` / BCM GPIO19. The duration is either an explicit
`reward_open_duration_ms` bench value or a resolved duration from a rig-specific
calibration profile. Legacy pulse durations must not be multiplied by six;
the fluid path must be recalibrated for continuous opening.

The production event sequence is `reward_command`, `reward_valve_on`,
`reward_valve_off`, and `reward_complete`. The latter records the measured
software ON interval and monotonic timestamps. The generic backend `pulse()`
method remains only an electrical-line test helper; reward delivery does not
call it and does not emit a pulse train.

The historical calibration workflow was the repeated-duration,
mass-before/after, CSV, and curve-plot approach in the
[SjulsonLab calibration.py reference](https://github.com/SjulsonLab/RPi4_behavior_boxes/blob/go_nogo/calibration.py).
The authoritative Pi 5 implementation is `rpi_vstim.tools.calibrate_reward`,
which uses the production `lgpio` backend, continuous openings, versioned JSON
profiles, CSV, and PNG output.
