# Configuration

`load_config(path)` reads TOML into frozen `Config` sections: `paths`,
`display`, `photodiode`, `hardware` (or legacy `gpio`), `operator_controls`,
`cameras`, `telemetry`, `session`, and `protocol`. Relative paths resolve from
the TOML file. Use `rpi-vstim config validate <file>` before a run.

`config/rigs/simulation.toml` uses fake display and simulated GPIO.
`pi5_default.toml` is a neutral Pi starting point; set its actual connector
and camera topology before hardware access. Box151's
`pi5_natural_image_demo.example.toml` has validated display, camera, GPIO,
corpus, and output choices. The real natural-image runner is Box151-gated;
generic protocols can use other profiles.

The schema rejects unknown fields, duplicate GPIO pins, BCM GPIO9, missing
stable identities for required experimental cameras, impossible static
display combinations, and incompatible experimental/simulation settings.
Live connectors and cameras are checked by discovery or at run time. Box151
production output is checked against its mounted NVMe before acquisition.
Generic profiles can point at any writable directory.
The supplied neutral profiles use temporary output for safe learning; choose
a persistent storage root before collecting real data. Package defaults use
`~/rpi_vstim/` and never point into the checkout.

Generic and simulation profiles set GPIO roles to `-1` (unassigned). Fill
verified BCM numbers before using those inputs or outputs on a new rig.

The inherited hardware dataclass contains the lab GPIO map for compatibility.
It does not claim or drive pins until a service is explicitly started. For a
new rig, verify each pin and output polarity before selecting `lgpio`.
