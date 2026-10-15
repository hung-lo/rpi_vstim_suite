# GPIO

The `hardware` TOML section selects `simulated` or `lgpio` and assigns BCM
pins. Validation rejects duplicates and preserves the exact guard:
`BCM GPIO9 is reserved for IRIG output.` Doctor never claims pins.
[gpio_input.py](../examples/gpio_input.py) requires an explicit input pin and
records edges without driving outputs.

Box151: licks are GPIO26 left, 27 right, 15 center; reward/pump lines are
19/20/21/7, airpuff 8, vacuum 25, operator button 23. GPIO24 is unused
trigger_out; GPIO4/10 are user pins and GPIO11 is header-only. GPIO9 belongs
exclusively to NeuroKairos. The left/right software lick path and physical
26/27 inputs were tested; center remains less validated. Reward/vacuum
software and line-level checks exist; complete fluidics, spout, water
calibration, and vacuum plumbing remain deployment-specific.

No example automatically toggles reward, vacuum, airpuff, or GPIO9. Output
control requires an explicit calibrated hardware task.
