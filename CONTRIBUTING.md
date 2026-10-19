# Contributing

This project is research software for a validated Raspberry Pi 5 setup. Before
changing a protocol or hardware path:

1. Branch from `main` and keep the change focused.
2. Keep protocol implementations additive and preserve their scientific
   defaults, timing assumptions, and session provenance.
3. Reuse the existing KMS display, camera, event, storage, and audio
   infrastructure. Do not create duplicate timing-critical subsystems.
4. Run the relevant tests (and the full suite when practical) before opening a
   pull request.
5. Use focused commits that make review and provenance clear.

A specialized task such as Go/NoGo may be developed in a separate repository
based on the same tested engine concepts; it does not have to be merged here.
Future compatibility with `rpi_rig_monitor` should use a shared
operator-control contract. That API is being developed separately and is not
part of the current `main` branch.
