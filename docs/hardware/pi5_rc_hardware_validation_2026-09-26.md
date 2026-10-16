# Pi 5 remote RC hardware validation — 2026-09-26

Branch: `codex/pre-hardware-rc-hardening`
Validated HEAD at start: `3c49ec1dff074888761bfe0f932f86031c4eb0fd`
Target: `pi@10.42.84.10` (`raspberrypi`)

This is bounded remote software/hardware evidence only. The user was not at
the rig, so this report makes no visual, optical, photodiode, or physical
acceptance claim.

## Target environment

- Debian GNU/Linux 13 (Trixie), aarch64.
- Kernel `6.12.75+rpt-rpi-2712`, PREEMPT.
- Python `3.13.5`.
- 2.0 GiB RAM; about 1.4 GiB available at baseline, 1.2 GiB minimum during
  the short combined smoke, and 1.3 GiB after cleanup.
- Baseline load `0.07 0.07 0.01`; combined-smoke samples `0.00–0.16`.
- Temperature was about 39.15°C before the display run, 40.25°C during the
  combined smoke, 40.80°C at its end, and 39.70°C at the final check.
- `vcgencmd get_throttled`: `0x0` at every recorded check.
- LightDM active; Wayland session 436 active; labwc PID 756533 remained alive;
  `/run/user/1000/wayland-0` existed; normal labwc DRM ownership returned after
  every display operation.

## Native and Python validation

The full Pi-native build ran in `/tmp/rpi-vstim-rc-kms-20260926` with:

```text
-O2 -Wall -Wextra -Wpedantic -Werror -std=c11
```

`kms_probe`, `drm_lease_selftest`, and `kms_frame_selftest` all built and
passed. The Pi Python run passed `211` tests under Python 3.13.5, compileall,
shell syntax checks, and the Pi preflight fixture config validation. Ruff was
not installed on the Pi; no package was installed for linting. The local
virtualenv Ruff run passed for the changed files; the full repository retains
its unrelated baseline findings.

Five hardware-free simulations completed and five generated sessions were
inspected: natural-images, reward-conditioning, spout-training,
drifting-gratings, and retinotopy. All were `COMPLETE` with no corrupt
artifacts.

## Corrected HDMI-A-2 300-frame trace

Raw trace: [`pi5_phase3_hdmi_a2_corrected_300_2026-09-26.json`](pi5_phase3_hdmi_a2_corrected_300_2026-09-26.json)

- Lease only: HDMI-A-2 / connector 42; HDMI-A-1 / connector 33 was not in the
  lease.
- Lease objects: `[42, 93, 104, 666]` (connector, primary plane, CRTC,
  cursor plane).
- Mode: `1024x600@59.8214`, RGB565; requested/completed `300/300`.
- `DRM_CAP_TIMESTAMP_MONOTONIC`: numeric value `1`, independently shown by
  `drm_info`; the native trace records `kernel_timestamp_clock=monotonic`.
- Kernel event sequence: `221407049–221407348`, contiguous; logical frames
  `0–299`, contiguous.
- Kernel-event intervals: mean `16,718.575 us`, median `16,716.000 us`,
  p95 `16,717.000 us`, p99 `17,374.000 us`, min/max `16,054/17,381 us`.
- Native missed vblank, estimated dropped, long, and short counts were all
  zero. The command returned 0 with empty stderr; no page-flip error or event
  wait timeout was observed.
- Every event carried `frame_index`, `buffer_index`, and explicit
  `photodiode_state`; buffer indices alternated 0/1 and photodiode state was
  even-frame `on`, odd-frame `off`. Metadata mismatches: `0`.
- Lease release completed with `restored=true`, `aborted=false`; labwc and
  both outputs were healthy afterward.

### Timestamp analysis boundary

The trace keeps the three timestamp streams separate:

- kernel-event intervals use `kernel_event_ns`;
- callback receipt intervals use `callback_monotonic_ns` and independently
  `callback_realtime_ns`; and
- callback-minus-kernel deltas use monotonic-versus-monotonic values only,
  because the capability reports monotonic kernel timestamps.

The audit found no producer, conversion, unit, or subtraction-direction bug:
the native callback uses `clock_gettime(CLOCK_MONOTONIC)`, converts the DRM
seconds/useconds pair to nanoseconds as `seconds * 1e9 + useconds * 1e3`, and
the analyzer computes callback minus kernel after selecting the matching clock.
The schema names those streams explicitly; the values are integer nanoseconds.

`DRM_CAP_TIMESTAMP_MONOTONIC` establishes the kernel event clock domain, not
the timestamp instant. A DRM page-flip event carries the kernel's vblank
timestamp, while `callback_monotonic_ns` is sampled when userspace dispatches
that event. On VC4, vblank timestamping also uses driver scanout-position
correction. Therefore a signed callback-minus-kernel value can be negative;
it is a clock/driver timestamp diagnostic, not callback latency without an
independent calibration.

For the standalone trace, callback monotonic intervals had mean/median
`16,716.022/16,716.151 us`, min/max `16,614.003/16,796.540 us`; realtime
intervals were equivalent. The callback-minus-kernel delta ranged from
`-663.763` to `+101.899 us` (median `-661.032 us`, mean `-648.778 us`; 295
negative samples; p95 `-655.661 us`). Excluding the five positive samples,
the delta median was `-661.035 us`, with 288/295 samples within `10 us` of
that median. Kernel intervals were `16,054–17,381 us` versus callback
intervals `16,614.003–16,796.540 us`; 290/299 interval differences were
within `20 us`, with nine compensating kernel-timestamp excursions. Reversing
the subtraction would leave five negative samples and would not correct the
interval excursions, so sign reversal alone is not valid. The stable interval
relationship provides no evidence of a clock-domain mismatch.

No optical timing is inferred.

## Live dual-camera identity resolution

Raw identity report: [`pi5_camera_identity_resolution_2026-09-26.json`](pi5_camera_identity_resolution_2026-09-26.json)

The production path now runs `rpicam-hello --list-cameras`, uses the topology
path as the configured stable identity, resolves uniquely by identity and
expected family, and passes the resulting numeric selector to `rpicam-vid`.
The live result was:

| Configured identity | Live topology / media | Current primary node | Selector |
|---|---|---|---:|
| `imx708_noir` `/base/.../i2c@88000/imx708@1a` | `platform:1f00110000.csi`, `/dev/media0` | `/dev/video8` | `0` |
| `imx708_wide_noir` `/base/.../i2c@80000/imx708@1a` | `platform:1f00128000.csi`, `/dev/media4` | `/dev/video0` | `1` |

Both one-second `rpicam-hello --nopreview` opens passed. A duplicate live
identity was explicitly rejected as ambiguous. No camera workers remained.

## SSD read-only discovery

The experiment SSD is **absent**. `lsblk -f` showed only the microSD-backed
`/dev/mmcblk0p1` boot partition, `/dev/mmcblk0p2` ext4 root mounted at `/`,
and zram swap. `blkid` is not installed. Neither `/mnt/behavbox_ssd` nor
`/mnt/hd` is mounted. Existing fstab intent remains:

```text
UUID=18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99 /mnt/behavbox_ssd ext4 defaults,nofail,x-systemd.device-timeout=10 0 2
```

No mount, write probe, fstab change, filesystem change, partitioning, or
formatting was performed. No storage preflight could pass, and no SD-card
fallback was used.

## Target-side preflight

Raw report: [`pi5_rc_preflight_2026-09-26.json`](pi5_rc_preflight_2026-09-26.json)

The safe Pi-5 preflight fixture reported protocol/config validity, `22` planned
events, `1,177` planned frames, deferred asset-root status, a bounded RAM
estimate of `38,993,920` bytes, both camera stable identities, lease-owned
HDMI-A-2/HDMI-A-1 display requirements, the `/mnt/hd` production-root
requirement with SD fallback rejected, and the five unvalidated hardware
gates. It never acquired hardware. The reward preflight no longer writes
assignment state under the configured production root; it uses a disposable
scratch root.

## Short combined integration smoke

Raw display trace: [`pi5_rc_combined_display_camera_2026-09-26.json`](pi5_rc_combined_display_camera_2026-09-26.json)
Resource/process log: [`pi5_rc_combined_display_camera_2026-09-26.log`](pi5_rc_combined_display_camera_2026-09-26.log)

This one no-animal smoke used the leased HDMI-A-2 production renderer and
both live-selected cameras. Cameras wrote only to `/tmp` for their bounded
8-second lifetime; there was no SSD recording. Display and both camera exit
statuses were `0`; each camera output grew to about 1.0 MiB. The display
completed `300/300` frames with lease objects `[42,93,104,666]`, kernel-event
mean interval `16,716.385 us`, min/max `16,051/17,381 us`, zero missed or
estimated dropped frames, zero metadata mismatches, `frame_source` external
raw pair, and `restored=true`. The callback stream remains diagnostic only.

At the sampled combined load, available RAM was about 1.2 GiB, load was
`0.00–0.08`, temperature was 40.25°C, and throttling was `0x0`. At cleanup,
available RAM was about 1.3 GiB, load was `0.16`, temperature was 40.80°C,
and no camera/KMS worker remained. labwc remained alive and both outputs
remained compositor-managed after release.

## Deferred until Monday physical presence

- Physical photodiode onset, polarity, luminance, and optical timing.
- Visual/physical screen acceptance and natural-image fidelity.
- SSD identity, mount, free space, write/fsync probe, and any sustained write.
- Sustained dual-camera recording and combined display/camera/SSD load.
- Long camera endurance and production stop-deadline acceptance.
- GPIO, reward valve, suction, lick input, TTL, and behavioral-session tests.
- Final-screen re-audit if the stimulus display changes.

No merge to `main` was performed.
