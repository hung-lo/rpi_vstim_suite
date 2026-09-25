# Pi 5 Phase 3 display ownership — 2026-09-25

This report records the live DRM/Wayland ownership topology and the safe
software work completed from commit `5b690e7 Implement standalone Pi 5 KMS
display probe` on branch `codex/phase-03-kms-display-ownership`.

No compositor, session, boot, storage, GPIO, reward, camera, or persistent
display configuration was changed. No lease was requested and no display was
taken over.

## Current ownership topology

Verified on the Pi with read-only `loginctl`, `ps`, `/proc`, `fuser`, ACL,
sysfs, and Wayland-client inspection:

| Item | Verified value |
|---|---|
| DRM display card | `/dev/dri/card1` (`vc4`); `/dev/dri/card0` is V3D |
| DRM owner | `labwc` PID `756533`, `/usr/bin/labwc -m` |
| compositor parent | LightDM session child PID `756524` |
| display manager | `lightdm.service`, PID `756515`, active |
| login/session | `pi`, active session `436`, `seat0`, Wayland, `rpd-labwc` |
| launch mechanism | LightDM autologin: `autologin-session=rpd-labwc`; session entry runs `/usr/bin/labwc-pi` |
| VT | session metadata reports `vc7`; tty1 login session 1 is inactive |
| Wayland socket | `/run/user/1000/wayland-0` |
| compositor DRM FDs | labwc holds multiple `/dev/dri/card1` FDs and render-node FDs |
| device ACL | `pi` has `rw` ACL on `/dev/dri/card1`; access is not the blocker |
| compositor helpers | `kanshi`, `pcmanfm`, `wf-panel-pi`, and `lwrespawn` also have card1 FDs |

The active compositor layout, read with `wlr-randr`, is:

| Output | DRM connector | Current mode | Position | Description |
|---|---|---|---:|---|
| stimulus role (provisional) | `HDMI-A-1`, connector 33 | `1024x600@59.821 Hz` | `0,0` | Lenovo LEN L1950wD |
| preview role (provisional) | `HDMI-A-2`, connector 42 | `1024x600@59.821 Hz` | `1024,0` | Addi-Data HDMI |

Both outputs are therefore managed by the same labwc DRM session. The role
labels in this historical pre-lease table were provisional and are superseded
by the physical mapping recorded in
`pi5_phase3_drm_lease_2026-09-25.md`: HDMI-A-2 is stimulus and HDMI-A-1 is the
camera monitor. The native
probe can enumerate both connectors, their CRTCs (92 and 104), and compatible
primary planes, but `drmModeSetCrtc()` is a modesetting ownership operation.
The real-hardware smoke attempt failed before modesetting with:

```text
DRM device is accessible but another session/compositor currently owns modesetting authority (DRM master); run outside that compositor or use a DRM lease
DRM access state: device_exists=true readable=true opened=true resources=enumerated connector=resolved mode=compatible crtc=resolved primary_plane=compatible modeset_authority=denied page_flips=not-tested
```

This is an ownership result, not a failure to discover or validate the DRM
resource topology. No page flip occurred and no restoration claim is made.

## DRM lease investigation

Installed stack:

```text
labwc 0.9.2-1+rpt4
libwlroots-0.19 0.19.1-1+rpt3
libwayland-client0 1.24.0-2~bpo13+1~rpt1
```

The active Wayland registry exposes:

```text
wp_drm_lease_device_v1 v1
```

A temporary read-only protocol client bound to that global and received the
compositor's non-master `drm_fd` event plus these connector offers:

```text
HDMI-A-2  connector_id=42  Addi-Data GmbH HDMI 0 (HDMI-A-2)
HDMI-A-1  connector_id=33  Lenovo Group Limited LEN L1950wD B3432845 (HDMI-A-1)
```

The client did not create a lease request, submit a lease, modeset, page flip,
or revoke anything. The result proves that this labwc/wlroots session exposes
both outputs as lease candidates. It does not yet prove that a submitted
HDMI-A-1-only lease will contain only the intended connector/CRTC/planes, nor
that timing and revocation/recovery work correctly.

Therefore HDMI-A-1 can theoretically be separated from HDMI-A-2 through the
available lease protocol, subject to a supervised lease-request test. The
protocol is staging/testing API surface; the production backend must verify
the leased object IDs with `drmModeGetLease()` before using them.

## Ownership strategy comparison

| Strategy | Fit for this rig | Timing/control | Main risk or missing work |
|---|---|---|---|
| **A. DRM lease** | Strong candidate: the live compositor advertises both connectors | Direct libdrm control of the leased stimulus resources while labwc can continue preview composition | Lease request/leased object set, page flips, revocation, and preview continuity are untested |
| **B. Dedicated experiment VT/session** | Reliable fallback if lease cannot provide a safe A1-only set | Full DRM master and direct KMS control | Requires a supervised session transition; normal GUI must relinquish card1 and be restored afterward |
| **C. Experiment owns both outputs** | Technically straightforward once direct master is available | Maximum control, including a native preview path | Loses labwc preview; requires implementing preview rendering and output lifecycle |
| **D. Wayland fullscreen** | Useful fallback/reference only | Can use compositor presentation feedback, but not direct KMS ownership | Compositor scheduling and output selection add uncertainty for frame/photodiode timing |

The recommendation is to pursue **A, DRM lease**, as the next supervised
hardware experiment. It best preserves the two-display requirement while
keeping the existing direct-libdrm stimulus path. If the lease request does
not produce an independently usable HDMI-A-1 resource set, use **B** as the
timing-validation architecture. **C** is a fallback only if a native preview
renderer is justified. **D** must remain a reference/fallback path, not the
timing-critical implementation.

## Exact next real-hardware test

Run only with the operator present and a rollback path visible:

1. Bind the already-exposed `wp_drm_lease_device_v1` global.
2. Request only the advertised HDMI-A-1 connector object.
3. Submit the lease and inspect its FD with `drmModeGetLease()`; verify the
   connector, required CRTC, and primary plane belong to the leased set.
4. Run a bounded one- or two-frame pattern first, then a short 60-frame test
   with the existing native probe adapted to the leased FD.
5. Verify HDMI-A-2 remains compositor-managed and visible through the Wayland
   session, then destroy the lease and verify HDMI-A-1 is re-advertised and
   labwc resumes it.

If leasing is rejected or the leased object set is unsuitable, the controlled
fallback procedure is a maintenance-window-only experiment: stop
`lightdm.service`, run the native probe from an exclusive VT, then start
`lightdm.service` and verify both outputs. This procedure is documented, not
executed; it would terminate the current graphical session and is outside the
safe autonomous boundary.

## Software hardening completed

- Native read-only output now reports separate device, resource, connector,
  mode, CRTC, primary-plane, modeset-authority, and page-flip states.
- Permission-denied modeset/page-flip failures identify compositor/DRM-master
  ownership explicitly and preserve the fact that no page flip occurred.
- Native timing output and Python timing summaries expose long intervals,
  short intervals, and estimated dropped-frame count instead of relying only
  on an average refresh estimate.
- Native results record the deterministic photodiode patch geometry/values and
  even-frame-on/odd-frame-off state; planned protocol events already preserve
  their intended `photodiode` state in session plans/events.
- Python maps compositor ownership failures to `NativeKmsOwnershipError` and
  preserves optional p95/p99, dropped-frame, and photodiode diagnostics.
- Existing connector roles, mode, refresh policy, and pixel format remain the
  configurable production surface. No speculative ownership enum was added.
- Partial initialization, bounded event storage, timeout/interrupted wait,
  page-flip failure, and restoration paths remain fail-closed; tests cover the
  ownership error, synthetic timing discontinuities, and injected native
  boundary failures for missing CRTC/plane, format, timeout, interruption, and
  restoration diagnostics. Direct ioctl fault injection remains deferred
  because it would require changing the live DRM owner or adding a test-only
  native harness.

## Validation and remaining gate

The native probe compiles warning-free on the Pi with the already-installed
Trixie libdrm headers. Local Python tests, compile checks, changed-file Ruff,
shell syntax, config validation, and all five protocol simulations are run as
part of this change. The Pi uses Python 3.13.5; the package was copied only to
`/tmp` for compile/import checks and no development environment was installed.

Canonical Gate 3 is **not passed**. Remaining blockers are:

- a supervised lease acquisition/object-set test or a dedicated DRM-master
  session;
- real page-flip timing and CRTC restoration under valid ownership;
- physical photodiode validation and timing correlation;
- production frame-cache rendering and the later integrated camera/GPIO work.

The experiment SSD remains intentionally absent, so production-storage
validation remains deferred and is not a Gate 3 result.
