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
is confirmed. The current physical mapping correction records BCM19 as the
reward pump and BCM25 as the vacuum; BCM7 remains unresolved/legacy `reward_4`
and BCM8 remains unresolved/legacy airpuff until separately tested. GPIO7’s
temporary vacuum use was test-only rewiring and is not the production map.
Function mapping and polarity remain separate fields, and polarity is not
inferred without physical confirmation.
