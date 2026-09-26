# Next lab acceptance checklist

This checklist is preparation only. It is not run from the Mac and does not
accept the SD card as production storage.

1. On the Pi, record the SSD block device, filesystem UUID, mount point, and
   free space. Refuse `/` and any SD-card path.
2. Run `rpi-vstim preflight --config <production.toml> --json` and save the
   report with the session records.
3. Run the native display probe and the short leased display smoke on the
   assigned visual connector. Preserve the existing HDMI-A-2 / connector 42
   visual assignment and HDMI-A-1 / connector 33 camera-monitor assignment.
4. Resolve both camera identities from stable topology data, then run the
   local dual-camera start/growth/stop check into a disposable SSD path.
5. Repeat display-only, camera-off, and combined display + dual-camera + SSD
   runs while recording RAM, CPU/load, temperature, throttling, page-flip
   intervals, camera output growth, and cleanup.
6. Validate GPIO/reward/lick wiring and water limits only after pin ownership,
   polarity, and pulse widths are confirmed by the hardware owner.
7. Photodiode validation remains deferred until a photodiode is available.

Every hardware result must retain the command, commit, config digest, storage
identity, camera resolution report, and raw timing trace. Historical traces are
not rewritten.
