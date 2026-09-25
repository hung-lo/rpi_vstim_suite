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

## Offline SIGSEGV diagnosis and preflight

The failed executable was the Pi build from `fe8eedf`, SHA-256
`31b75b41122292a12dacd2dfea52c0ceb9bd9bf330c195b7510016ecd66415e4`. The Pi
does not have `coredumpctl`, and no core or useful kernel fault record was
available, so there is no native backtrace. The fault is nevertheless
identified exactly from the protocol binding and the event-dispatch behavior.

The authoritative DRM-lease v1 protocol (the staging
`drm-lease-v1.xml`, audited 2026-09-25) declares one request on each of
`wp_drm_lease_connector_v1` and `wp_drm_lease_v1`: their `destroy` requests.
The original hand-written binding declared both interfaces with zero requests.
Wayland dispatches events after the interface's request count; that shifted
connector callbacks by one and made the final `withdrawn` event address past
the five-entry listener metadata. This explains the status-139 crash during
the first connector enumeration, before any result was printed.

The fix in `native/kms_display/drm_lease.c`:

- declares the missing destructor request on both interfaces;
- marks `request.submit` and lease/connector destroys with the destructor
  marshal flag;
- treats device `release` as a normal request and waits for the server's
  `released` event before freeing the device context;
- validates complete connector offers and closes withdrawn/overflow offers;
- factors enumeration into `drm_lease_discover()` so preflight does not submit
  a lease request; and
- adds a native protocol-metadata self-test.

`wayland-scanner` and the protocol XML are not installed on the Pi, so this
small binding remains hand-maintained; its interface counts, signatures,
listener order, and v1 version are checked against the authoritative XML and
the native self-test. The generic listener casts are the libwayland client ABI
required by `wl_proxy_add_listener`; each callback has the exact protocol
signature and listener order rather than an untyped callback adapter.

The local native self-test passed under ASan/UBSan (LeakSanitizer was disabled
because it cannot run under this environment's ptrace sandbox). The Pi build
also passed the same sanitizer self-test. The Pi's new enumeration-only command
completed successfully:

```text
{
  "ownership": "lease-available",
  "requested_connector": "HDMI-A-1",
  "drm_fd_received": true,
  "offers": [
    {"name":"HDMI-A-1","connector_id":33,"withdrawn":false},
    {"name":"HDMI-A-2","connector_id":42,"withdrawn":false}
  ]
}
```

The actual machine-readable output was JSON. This command binds and enumerates
the lease device, then releases it; it does not call `submit`, request a lease
fd, modeset, page-flip, or alter either display. Afterward labwc PID `756533`
and active session `436` remained running, and both HDMI outputs remained
enabled at `1024x600@59.820999 Hz`.

The offline preflight gate is now satisfied. The supervised lease retry was
intentionally deferred to the user-supervised step and must still begin with
the minimal request/release sequence below; it must not be treated as a lease
validation until it succeeds:

```bash
./kms_probe --lease --connector HDMI-A-1 --width 1024 --height 600 \
  --refresh 59.82 --format RGB565 --probe-only --json
```

If that request fails, capture its status and stderr, verify labwc and both
outputs, and stop. Do not retry repeatedly or proceed to page flips.

## First post-fix supervised lease validation

This supervised run used the corrected client from commit `4134739`. No
LightDM, labwc startup, boot, autologin, persistent display, storage, camera,
GPIO, reward, or session configuration was changed.

### Preflight

Captured at `2026-09-25T14:14:08.211443738-04:00`:

| Item | Verified value |
|---|---|
| active session | Wayland session `436`, user `pi`, `seat0`, active |
| compositor | labwc PID `756533`, `/usr/bin/labwc -m` |
| HDMI-A-1 | enabled, current `1024x600@59.820999 Hz`, connector 33 |
| HDMI-A-2 | enabled, current `1024x600@59.820999 Hz`, connector 42 |
| mapping | HDMI-A-1 stimulus, HDMI-A-2 camera preview |
| DRM master before request | labwc on `/dev/dri/card1` |

Fresh direct read-only probes confirmed HDMI-A-1 connector 33 / CRTC 92 and
HDMI-A-2 connector 42 / CRTC 104 before the lease request.

### Lease request and object inspection

The exact probe ran at `2026-09-25T14:14:19.152133618-04:00` and completed at
`2026-09-25T14:14:19.381598406-04:00` with status 0 (227 ms):

```text
./kms_probe --lease --connector HDMI-A-1 --width 1024 --height 600 \
  --refresh 59.82 --format RGB565 --probe-only --json
```

The granted lease reported:

```json
{
  "connector": "HDMI-A-1",
  "connector_id": 33,
  "crtc_id": 92,
  "lease_objects": [33, 81, 92, 655],
  "selected_mode": "1024x600@59.8214",
  "modeset": false,
  "page_flip": false
}
```

The lease object set is consistent with the requested output: connector 33,
primary plane 81, CRTC 92, and cursor plane 655. HDMI-A-2 was not requested.
The native debug lifecycle showed lease fd receipt, lease release, and the
device `released` acknowledgment.

### Release and compositor recovery

After cleanup, checked at `2026-09-25T14:14:33.160993478-04:00`:

- labwc PID `756533` was still running;
- session 436 remained active on Wayland seat0;
- HDMI-A-1 and HDMI-A-2 were both enabled at `1024x600@59.820999 Hz`;
- `wlr-randr` remained usable for both outputs; and
- `/dev/dri/card1` was again held by labwc and its normal desktop helpers.

The client completed the release lifecycle within the 227 ms probe run. No
independent compositor-recovery timestamp was taken between process exit and
the post-check, so the exact sub-second restoration interval is not claimed.

This validates HDMI-A-1-only lease acquisition, a usable leased fd and object
set, HDMI-A-2 compositor continuity, and clean lease release. It does not
validate modesetting, page flips, frame timing, photodiode timing, or
production rendering.

## Validation completed before retry

- WSL development environment: Python `3.11.16`; full pytest `118 passed`,
  compileall, shell syntax, changed-file Ruff, and the five-protocol simulation
  contract passed.
- Pi runtime: Python `3.13.5`; `compileall`, package import checks, and the
  hardware-independent lease/native-probe tests passed (`17 passed`). Pytest
  was already installed on the Pi; no package was installed by this debug
  work.
- Native warning build and ASan/UBSan self-test passed locally and on the Pi.
- `wayland-scanner`, `coredumpctl`, and Valgrind are unavailable on the Pi;
  `gdb` is present, but no core was available to inspect.

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

This historical section validates only that the surrounding compositor/session
remained intact after the failed client attempt. It does **not** describe the
successful post-fix lease probe above.

The first hardware lease subtask was stopped before the supervised retry. The
post-fix supervised probe has now validated lease acquisition, object
inspection, and release; no page-flip, failure-path, or timing test was
attempted.

Canonical Gate 3 remains not passed. The first supervised lease/recovery probe
passed, but physical modeset/page-flip timing, photodiode timing, production
frame rendering, SSD/storage validation, and integrated display/camera/GPIO
acceptance remain pending.
