# Pi 5 reward calibration

## What is being calibrated

The canonical output is `reward_left` / BCM GPIO19. The unified delivery mode
is `single_continuous_open`: one behavioral reward drives one active interval
and then returns to the configured inactive electrical level. This is
deliberately different from the legacy `vstim_natural_img_reward` six-pulse
train. Old pulse durations cannot be converted by multiplying by six; the
water path must be measured again.

The historical workflow used repeated solenoid durations, a vessel mass before
and after each batch, CSV output, and a calibration plot. The new tool keeps
that useful measurement workflow but uses the production Pi 5 `lgpio` backend
and never generates an internal pulse train:

```bash
PYTHONPATH=src python -m rpi_vstim.tools.calibrate_reward \
  --config config/rigs/pi5_reward.toml \
  --output-dir /mnt/hd/reward-calibration/2026-XX-XX \
  --rig-id rig-01 --calibration-id rig-01-2026-XX-XX \
  --durations-ms 50,75,100,125 --delivery-count 100 --execute
```

`--execute` is mandatory because the command drives GPIO19. Warm-up deliveries
are optional. For each measured duration, the operator supplies collection mass
before and after the batch. The approximation is:

```text
collected_water_ul ~= collected_mass_g * 1000
mean_uL_per_reward = collected_water_ul / delivery_count
```

The command writes a versioned JSON profile, CSV, and PNG curve. The checked-in
`calibrations/reward/example_single_continuous_open.json` is synthetic and is
not a rig calibration or a claim about delivered volume.

## Audit and migration

The current production tree contains no `reward_num_pulses`,
`reward_pulse_count`, `reward_pulse_on_sec`, `reward_pulse_off_sec`, or
`pulse_index` fields. The generic `LgpioBackend.pulse()` method and its GPIO
line-validation test remain electrical test helpers only. Historical planning
documents and the frozen legacy-source notes still mention pulse timing and
the old reward profile; they are reference/audit material, not production
configuration. The config loader rejects those legacy field names, including
when nested in protocol parameters, and never multiplies a legacy duration by
six.

## Profile contract

Profiles contain `schema_version`, calibration identity, creation time, rig,
operator, `reward_left`, GPIO19, `single_continuous_open`, fluid, raw measured
conditions, valid duration and volume ranges, a piecewise-linear interpolation
model, linear-fit diagnostics, software commit, and backend metadata. A
production session may configure:

```toml
[hardware]
reward_target_ul = 3.0
reward_calibration_profile = "../../calibrations/reward/rig-specific.json"
```

At startup the resolver validates the role, GPIO, delivery mode, and target
range, then freezes the resolved duration. Requests outside the measured
volume range fail closed; no extrapolation is performed. The session can write
the resolved duration, calibration ID, profile SHA-256, and creation date to
`provenance.json` with `SessionOutput.write_reward_provenance()`.

## Current hardware status

GPIO19 electrical control was validated on the prototype, but the real reward
plumbing is not attached. No water-volume calibration has been performed and no
calibration values are inferred from legacy numbers. Final physical work must
measure the rig-specific water delivery, verify active polarity and safe
startup/shutdown, and retain the generated profile with the session records.
