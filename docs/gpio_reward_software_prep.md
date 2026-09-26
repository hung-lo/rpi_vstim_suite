# GPIO/reward software preparation

No GPIO or reward hardware was accessed during the overnight Mac run. The
existing simulated hardware worker keeps reward, suction, lick, and optional
TTL outputs safe and the configuration validator rejects conflicting BCM pin
assignments.

The future boundary remains one dedicated hardware worker owning all pins. It
will receive bounded commands and emit timestamped status/events; camera and
display workers must not own GPIO or run reward logic. Required software
contracts include safe inactive startup, explicit `SAFE`/`SHUTDOWN`, bounded
command handling, reward/water-limit state, lick-edge events, and cleanup that
cannot be blocked by camera failure.

Pin numbers, electrical polarity, pulse widths, water limits, and actuation
acceptance remain deferred until the authoritative Pi hardware configuration
is confirmed. No pin mapping is guessed here.
