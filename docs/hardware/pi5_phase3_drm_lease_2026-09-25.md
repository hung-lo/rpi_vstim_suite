# Pi 5 Phase 3 DRM lease validation — 2026-09-25

This was the first supervised DRM lease attempt from commit `2decefa` on
branch `codex/phase-03-kms-display-ownership`.

The test was intentionally short and used only the provisional stimulus role:

```text
HDMI-A-1 = requested leased stimulus output
HDMI-A-2 = labwc-managed preview output
```

No LightDM, labwc startup, boot, autologin, persistent display, storage,
camera, GPIO, reward, or session configuration was changed.

## Pre-lease state

Captured immediately before the request at `2026-09-25T13:37:23-04:00`:

| Item | Value |
|---|---|
| labwc | PID `756533`, `/usr/bin/labwc -m` |
| session | LightDM session `436`, `pi`, `seat0`, active Wayland `rpd-labwc` |
| DRM card | `/dev/dri/card1`, labwc DRM master |
| HDMI-A-1 | connected, enabled, current `1024x600@59.820999 Hz`, position `0,0` |
| HDMI-A-2 | connected, enabled, current `1024x600@59.820999 Hz`, position `1024,0` |
| direct KMS resources | HDMI-A-1 connector 33, CRTC 92, primary plane 81 |
| lease protocol | `wp_drm_lease_device_v1` v1 exposed; prior read-only enumeration offered connector 33 and connector 42 |

The pre-lease `fuser` result showed labwc and its desktop helpers using
`/dev/dri/card1`. The direct read-only native probe still resolved HDMI-A-1
without attempting modesetting.

## Lease client and request

The repository now contains an isolated native Wayland lease client in
`native/kms_display/drm_lease.c`. It is designed to:

1. bind the exposed lease device;
2. enumerate offers and select exactly the configured connector;
3. request only that connector;
4. return the lease fd to the existing native KMS path; and
5. validate the returned object list with `drmModeGetLease()` before a modeset.

The Python side has a small ownership lifecycle model and mocked tests for
exact selection, ambiguity, withdrawal, denial, revoked leases, compositor
disconnect, and lease-fd failure.

The supervised command was a probe-only HDMI-A-1 lease request. It did not
request HDMI-A-2, modeset, allocate KMS buffers, or page-flip.

## Result: blocked by native client fault

The probe terminated with:

```text
Segmentation fault
status=139
```

No lease object set was safely reported, so the following remain **unverified**:

- lease success;
- exact connector/CRTC/primary-plane object set;
- lease fd usability;
- native page flips or timing;
- lease revocation behavior;
- normal lease release timing.

Per the supervised-test safety boundary, no retry was made and no page-flip
test was attempted.

## Post-fault recovery evidence

Immediately after the process exited:

- labwc PID `756533` was still running;
- session 436 remained active on seat0;
- HDMI-A-1 and HDMI-A-2 remained enabled at `1024x600@59.820999 Hz`;
- `wlr-randr` remained usable and reported both outputs;
- no reboot or session restart occurred;
- no core file or useful kernel fault record was present under `/tmp` or in the
  recent kernel log.

Because the probe was probe-only and did not reach a verified KMS modeset, no
visible compositor recovery interval can be claimed. The outputs were
immediately queryable in their pre-test compositor state after process exit.

## Gate and next action

This validates only that the surrounding compositor/session remained intact
after the failed client attempt. It does **not** validate DRM leasing, native
page flips, or timing.

The hardware lease subtask is stopped. The next action requires offline native
client debugging and a supervised rerun only after the segmentation fault is
eliminated by software tests/review. No page-flip, failure-path, or repeated
lease acquisition was attempted.

Canonical Gate 3 remains not passed. Physical photodiode timing, production
frame rendering, SSD/storage validation, and integrated display/camera/GPIO
acceptance remain pending as well.
