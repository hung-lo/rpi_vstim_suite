# Pi 5 physical visual acceptance — 2026-09-29

Status: partial visual acceptance. GPIO/wiring inspection was deferred at the
operator's request because the rig is not connected to the lick spout, reward,
or suction systems. SSD/storage acceptance was not performed.

## Hardware path

- Target: Raspberry Pi 5 `raspberrypi`, Python 3.13.5.
- Stimulus: HDMI-A-2 / connector 42, selected at `1024x600@59.82 Hz`.
- Preview: HDMI-A-1 / connector 33, read-only inventory reported connected.
- Renderer: repository `KmsDisplayBackend` and `ProductionFrameRenderer`,
  leased native KMS path.
- Temporary source, packed frames, and test staging were under Pi `/tmp`,
  confirmed `tmpfs`, and removed after the run.
- No SSD, GPIO output, reward, suction, lick actuation, or camera capture was
  used.
- All 32 bounded visual stages completed without software abort. Afterward,
  `labwc` remained alive, no `kms_probe` or `rpicam` process remained, and
  `vcgencmd get_throttled` returned `0x0`.

The branch does not yet expose a unified real production-session runner for
these protocols; this was a physical production-renderer smoke using a small
temporary representative image set and generated geometry patterns. It is not
claimed as full protocol acceptance.

## Operator observations, verbatim

> ok seems working, I can see all 3 things popping up on the right screen. the vstim looks not exactly waht I expected though, but assusming this is just testing i think it looks ok. The grating only seem vertical and horizontal? and the retinotopy I can see some bands but not going through the whole screen. on this rig the lick spout is not yet connected.

## Acceptance interpretation

| Check | Result |
|---|---|
| Correct stimulus screen | Visually identified by operator as the right screen; run was HDMI-A-2 / connector 42. |
| Initial/final gray | Not separately confirmed in the operator statement. Software stages completed. |
| Images visible | Confirmed by operator. |
| Image scaling/cropping | Operator said appearance was not exactly expected; unresolved. |
| Image transitions/stale/flash frames | Not separately confirmed; no software abort. |
| Photodiode corner patch | Not visually confirmed. No optical timing inference is made. |
| HDMI-A-1 monitor stability | Not separately confirmed. |
| Restore after exit | Software cleanup completed; visual restore not separately confirmed. |
| Drifting-grating orientation/direction | Operator saw only vertical/horizontal appearance; unresolved and not accepted. |
| Drifting-grating smoothness/contrast/tearing | Not separately confirmed; not accepted as a full smoke. |
| Retinotopy geometry | Bands were visible, but operator reported they did not go through the whole screen; unresolved/blocking. |
| Retinotopy direction/gray/trails | Not separately confirmed. |

## GPIO and wiring status

No physical wiring was inspected or confirmed today. Per the operator, this
rig is not connected to the actual lick spout, reward system, or suction
system. The current GPIO preflight source-audit mappings remain source/config
evidence only; the preflight document was not changed to claim physical wiring.

No output pins were configured or toggled. No reward or suction was delivered
or activated.

## Phase 5 disposition

Phase 5 should remain blocked for:

1. visual protocol acceptance: the operator observed unexpected grating
   orientation coverage and incomplete retinotopy traversal;
2. image geometry/scaling follow-up;
3. full unified production-session integration, which is not present in this
   branch; and
4. GPIO/reward/suction bring-up until the physical rig is connected and the
   harness is inspected.

SSD/storage work remains intentionally out of scope.
