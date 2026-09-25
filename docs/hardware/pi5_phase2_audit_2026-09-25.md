# Pi 5 Phase 2 read-only audit — 2026-09-25

Target: `pi@10.42.84.10`
Remote host: `raspberrypi`
Audit command: `./scripts/audit_pi5.sh pi@10.42.84.10`
Result: exit status `0`

The audit and follow-up discovery commands were read-only. No packages,
boot files, groups, permissions, services, GPIO outputs, or reboot state were
changed. No camera capture was started.

## Verified inventory

| Area | Result |
|---|---|
| Hardware | Raspberry Pi 5 Model B Rev 1.0 |
| OS | Debian GNU/Linux 13 (trixie), aarch64 |
| Python | `/usr/bin/python3`, Python 3.13.5 |
| Kernel | `6.12.75+rpt-rpi-2712`, PREEMPT, aarch64 |
| Memory | 2.0 GiB RAM; 2.0 GiB swap |
| Temperature/throttle | 38.4 °C at follow-up; `throttled=0x0` |
| Root storage | `/dev/mmcblk0p2`, ext4, 29 GiB total, 19 GiB free, mounted `/` read-write |
| Intended storage | `/mnt/hd` is not mounted and was not found in the mount inventory |
| Time | System clock synchronized; NTP service active; UTC/EDT and RTC consistent |
| Network | `eth0` up at `10.42.84.10/23`; `wlan0` down |
| Runtime tools | `pip3`, `ffmpeg`, `udevadm`, `media-ctl`, `v4l2-ctl`, `rpicam-hello`, `lsusb` present |
| Python modules | `lgpio`, `gpiozero`, and `PIL` import specs present |

## Display and DRM

Present nodes, readable by the `video`/`render` device groups:

```text
/dev/dri/card0       root:video  226,0
/dev/dri/card1       root:video  226,1
/dev/dri/renderD128  root:render 226,128
/dev/fb0             root:video  29,0
```

Loaded modules include `vc4` and `drm`.

```text
card1-HDMI-A-1: connected, enabled, DPMS On
card1-HDMI-A-2: connected, enabled, DPMS On
```

`HDMI-A-1` advertises `1024x600`, `1920x1080` variants, `1280x1024`,
`1440x900`, `1280x720` variants, and lower modes. `HDMI-A-2` advertises only
`1024x600`. The read-only sysfs inventory does not expose the active refresh
rate, and the intended physical connector/mode was not independently
confirmed.

Missing display-discovery tools: `modetest`, `drm_info`, `edid-decode`, and
`kmscube`. No KMS probe or display implementation was started.

## GPIO

The Pi exposes `/dev/gpiochip0`, `gpiochip10`, `gpiochip11`, `gpiochip12`,
and `gpiochip13` (`gpiochip4` is a symlink to `gpiochip0`). The `pi` account
is in `gpio`, `video`, and `render`, and the device nodes are group-readable
and group-writable according to the audit snapshot.

This establishes device presence and account membership only. No pin mapping
for reward, suction, lick, or TTL was physically validated, and no GPIO line
was requested or toggled.

## Physical camera inventory

The many `/dev/video*` nodes are CSI pipeline nodes, not many physical
cameras. `rpicam-hello --list-cameras` identified exactly two sensors:

| Logical candidate | Sensor identity | Stable topology | Primary capture node |
|---|---|---|---|
| `imx708_noir` | `/base/axi/pcie@1000120000/rp1/i2c@88000/imx708@1a` | `platform:1f00110000.csi`, `/dev/media0`; udev path `platform-1f00110000.csi-video-index0` | `/dev/video8` |
| `imx708_wide_noir` | `/base/axi/pcie@1000120000/rp1/i2c@80000/imx708@1a` | `platform:1f00128000.csi`, `/dev/media4`; udev path `platform-1f00128000.csi-video-index0` | `/dev/video0` |

Each sensor reports:

```text
SRGGB10_CSI2P  1536x864   120.13 fps  (768,432)/3072x1728 crop
SRGGB10_CSI2P  2304x1296   56.03 fps  (0,0)/4608x2592 crop
SRGGB10_CSI2P  4608x2592   14.35 fps  (0,0)/4608x2592 crop
```

The corresponding media topologies identify `imx708_noir` on
`1f00110000.csi` and `imx708_wide_noir` on `1f00128000.csi`. The primary
nodes expose V4L2 capture formats including YUYV/UYVY/YVYU/VYUY, RGB formats,
Bayer formats, grayscale formats, and PiSP compressed formats. No stream was
started, so concurrent capture performance and negotiated production modes
remain unverified.

USB topology contains audio and HID devices only; the two cameras are CSI,
not USB cameras.

`libcamera-hello` is unavailable; `rpicam-hello` is available and provided the
sensor enumeration above.

## Storage and load evidence

The configured plan path `/mnt/hd` is absent. Only the 29 GiB microSD-backed
root filesystem was observed, with 19 GiB free at audit time.

No write benchmark was run because this was required to remain a read-only
audit. Therefore there is no baseline sequential-write result and no
concurrent dual-camera write-throughput result. Camera recording, storage
latency, memory pressure, thermal behavior, display timing, and GPIO timing
under simultaneous load remain untested.

## Comparison with V2 plan assumptions

| V2 assumption | Verified result | Status |
|---|---|---|
| Pi 5, 64-bit Debian Trixie, Python 3.13.x | Pi 5, Debian 13/Trixie, aarch64, Python 3.13.5 | Matches |
| Direct DRM/KMS is available | DRM nodes, `vc4`, connectors, and modes are present | Hardware present; active mode/refresh and page-flip behavior unverified |
| One intended HDMI display/profile | Two HDMI connectors report connected; `HDMI-A-1` includes the 1280x720 candidate and `HDMI-A-2` only reports 1024x600 | Not resolved |
| Two local cameras with stable identities | Two IMX708 CSI sensors mapped to media topology and udev paths | Identity/topology verified; simultaneous capture unverified |
| `/mnt/hd` is writable experiment storage | `/mnt/hd` is not mounted | Fails |
| Camera/storage load fits the 2 GiB Pi | No write or concurrent capture test performed | Unverified |
| GPIO access without root | `pi` has relevant groups and device nodes are present | Access appears provisioned; runtime ownership/timing unverified |
| Synchronized system clock | `timedatectl`: synchronized, NTP active | Matches |
| Production tools available | Camera and GPIO-related tools/modules are present; KMS discovery tools are missing | Partial |

## Gate 2 assessment

Canonical Gate 2 is **not satisfied**.

Blocking findings:

1. The plan’s required `/mnt/hd` target storage is not mounted.
2. No storage write-throughput or concurrent dual-camera throughput evidence
   exists under the read-only restriction.
3. The intended HDMI connector, active mode, refresh rate, and physical
   screen geometry are not verified; two connectors are currently reported
   connected.
4. KMS discovery tools are missing, and no display backend proof was run.
5. Runtime no-root access and camera capture behavior were not exercised.

Canonical production Phase 3 remains gated. The later SSD-deferred addendum
authorizes only scoped, storage-independent display discovery and interface
work; that work is recorded below and does not satisfy the full Gate 2.

## Phase 2 follow-up — bootstrap and readiness characterization

### Storage resolution

The follow-up read-only inventory reported:

```text
/dev/mmcblk0p1  vfat  label=bootfs  UUID=F587-071F
/dev/mmcblk0p2  ext4  label=rootfs  UUID=d6944274-f2f7-4644-96a4-213c3b367f5c  mounted /
/dev/zram0      swap  label=zram0   UUID=20aac603-2cb2-4b4b-a7d1-2accb041d441
```

`blkid` is not installed; `lsblk -f` and `/dev/disk/by-uuid` provided the
filesystem identity above. The only non-root storage entry in `/etc/fstab` is:

```text
UUID=18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99 /mnt/behavbox_ssd ext4 defaults,nofail,x-systemd.device-timeout=10 0 2
```

That UUID is absent from `lsblk`, `/dev/disk/by-uuid`, and the current mount
table. `/mnt/behavbox_ssd` exists as an empty root-owned directory but is not
mounted. The repository configuration separately names `/mnt/hd`; neither
`/mnt/hd` nor an `/mnt/hd` fstab entry exists on the Pi.

The intended experiment backing device is therefore not present, and there is
no unambiguous basis for mapping it to `/mnt/hd`. No mount, directory,
filesystem, or `/etc/fstab` change was made. The root microSD filesystem was
not substituted for experiment storage.

### Diagnostic packages installed

Trixie package metadata was inspected before installation. The minimal set
selected was:

| Package | Version | Reason |
|---|---|---|
| `libdrm-tests` | `2.4.134-3~bpo13+1+rpt1` | Provides `modetest` |
| `drm-info` | `2.6.0-2+b1` | DRM resources/properties/connector inspection |
| `edid-decode` | `0.1~git20241119.5332a3b-1` | EDID decoding |

The transaction used `sudo -n apt-get install -y --no-install-recommends` and
installed five new packages:

```text
drm-info
edid-decode
libdrm-etnaviv1
libdrm-tegra0
libdrm-tests
```

It upgraded these required libdrm packages from
`2.4.131-1~bpo13+1+rpt2` to `2.4.134-3~bpo13+1+rpt1`:

```text
libdrm-amdgpu1
libdrm-common
libdrm-nouveau2
libdrm-radeon1
libdrm2
```

`kmscube` has a Trixie candidate (`0.0.0~git20210103-1+b3`) but was not
installed: it is an EGL/GBM example application, not required for the
read-only EDID/mode/resource discovery completed here. No desktop environment
or unrelated graphics stack was installed.

### DRM connector, EDID, and active-mode findings

The display-capable node is `/dev/dri/card1` on the `vc4` driver. `card0` is
the V3D node; `drm_info` reports `DRM_IOCTL_MODE_GETRESOURCES: Operation not
supported` for it, while `/dev/dri/card1` is fully inspectable. The card1
connectors report link status `Good` and DPMS `On`:

| Connector | EDID identity | Preferred/native mode | Current active mode | Other relevant modes |
|---|---|---|---|---|
| `HDMI-A-1` | `LEN`, model `4230`, product `LEN L1950wD`, EDID size 154x86 mm | `1024x600@59.821429` | `1024x600@59.82`, CRTC 92 | `1280x720@60.00`, `1280x720@59.94`, `1280x720@50.00`, plus 1080p and lower modes |
| `HDMI-A-2` | `ADA`, model `8448`, product `HDMI`, EDID size 476x268 mm | `1024x600@59.821429` | `1024x600@59.82`, CRTC 104 | `1024x600` only |

Both connectors are physically reported `connected`, `enabled`, and active.
The repository’s candidate `HDMI-A-1`, `1280x720@60.0` profile is not the
current or preferred mode. The two connected displays and their differing EDID
identities still require an operator/hardware decision about which physical
output is the experiment display. No mode was set and no full-screen output was
started.

### Raspberry Pi camera stack and smoke tests

Installed commands:

```text
rpicam-hello  rpicam-jpeg  rpicam-raw  rpicam-still  rpicam-vid
```

They are owned by `rpicam-apps-core`. Version output is:

```text
rpicam-apps build: v1.11.1 02-02-2026
libcamera build: v0.7.0+rpt20260205
capabilities: egl:1 qt:1 drm:1 libav:1
```

`libcamera-hello` is unavailable, but the installed modern `rpicam-*` stack
provides the required enumeration/open functionality. Both cameras were
individually opened with:

```text
rpicam-hello --camera N --timeout 1000 --nopreview
```

Results:

| Camera index | Sensor/topology | Result | Selected stream |
|---:|---|---|---|
| 0 | `imx708_noir`, `/base/.../i2c@88000/imx708@1a`, `/dev/media0` | Pass, exit 0 | 2304x1296 YUV420 plus PiSP raw |
| 1 | `imx708_wide_noir`, `/base/.../i2c@80000/imx708@1a`, `/dev/media4` | Pass, exit 0 | 2304x1296 YUV420 plus PiSP raw |

Both smoke tests used no preview and no output file. The stack logged warnings
that static sensor properties and sensor delays are unavailable, but loaded
the corresponding IMX708 tuning files, configured both streams, and exited
successfully. This is an individual-open result, not dual-camera load
acceptance.

### Phase boundary

Phase 2 bootstrap changes performed: installation of the three selected
diagnostic packages and their required libdrm dependencies only.

No mount or persistent configuration change was made. No mode-setting
operation, page-flip test, full-screen stimulus, or production camera
supervisor was started. The later addendum-authorized scoped display-only
software work is described below.

Remaining Phase 3 work is the standalone KMS/DRM probe and backend implementation.
Later integrated-load work remains the intended-storage write test, concurrent
dual-camera recording/resource characterization, and display/GPIO/camera
contention acceptance.

## Updated Gate 2 assessment

Canonical Gate 2 remains **not satisfied**.

Verified readiness now includes:

- Pi 5, Debian Trixie, Python 3.13.5, DRM card/connector resources, and
  synchronized time.
- Two stable CSI IMX708 identities and individual `rpicam` open smoke tests.
- Read-only EDID, preferred-mode, available-mode, connector-status, and
  active-mode characterization.
- Minimal DRM diagnostic tooling installed.

Remaining blockers:

1. The fstab-referenced UUID `18d6cbdf-378a-4b0a-a3fb-15c23b4eeb99` is not
   present, so the intended experiment storage cannot be mounted or tested.
2. `/mnt/hd` has no existing device mapping. The user has supplied a
   provisional software role mapping, but the physical experiment display has
   not been independently re-verified.
3. No target-storage write/read throughput result exists.

Concurrent dual-camera load acceptance is intentionally not a Gate 2 blocker
for this report; it remains later integrated-load validation. Canonical
production Phase 3 and final display acceptance remain deferred. The
addendum-authorized scoped display-only work has not set a mode, taken DRM
master, presented a frame, or performed timing acceptance.

## Validation location and result

Repository validation was run in the local WSL workspace, not on the Pi:

```text
python3 -m compileall -q src tests   PASS
python3 -m pytest -q                 NOT RUN: pytest module unavailable
ruff check .                         NOT RUN: ruff unavailable
```

The local WSL validation environment was subsequently restored in the repo
`.venv` with the project’s declared development dependencies; the results of
that validation and the scoped display-only software work are recorded below.

## Addendum-authorized scoped display-only work — 2026-09-25

The SSD is intentionally absent and production-storage validation is deferred.
The user-authorized provisional roles are `HDMI-A-1` for visual stimulation
and `HDMI-A-2` for camera preview; both remain configurable and are not a
physical cable assignment claim.

Software-only changes now provide:

- explicit stimulus/preview connector configuration, including preview
  disablement and exact-versus-nearest refresh policy;
- hardware-independent `modetest -c` parsing and strict connector/mode/refresh
  selection with no fallback;
- `rpi-vstim hardware display-probe`, which invokes the installed read-only
  `modetest -M vc4 -c` path and does not set modes or present frames;
- a Python KMS boundary backed by the standalone native test-pattern/page-flip
  path;
- stable camera identity resolution by topology/sensor path rather than
  transient `/dev/videoN` numbering; and
- explicit storage inspection that never mounts or changes a path.

Real-Pi validation remains limited to the earlier read-only DRM/EDID output
and individual `rpicam` open smoke tests. No repository code was deployed to
the Pi, no display was taken over, and no full-screen/no-mouse stimulus smoke
test was run.

Remaining scoped display work is ownership-permitted page-flip/vblank
validation, physical photodiode measurement, and production frame-cache
integration. The SSD-dependent storage throughput test, concurrent camera load
test, and final integrated acceptance remain deferred.

## Final Gate 2 assessment after the addendum

Canonical Gate 2 remains **not satisfied overall**. The storage sub-gate is
deferred because the experiment SSD is absent; no SD-card fallback was used.
Display discovery and camera enumeration are sufficiently characterized for
the scoped software work, but native presentation/timing and integrated load
acceptance remain unverified.

Validation was run locally in the WSL repository environment, not on the Pi:

```text
interpreter: repository .venv, Python 3.11.16 (system Python 3.13 was unavailable)
pytest: 91 passed
compileall: PASS
focused Ruff on changed files: PASS
bash -n scripts/*.sh: PASS
five simulation entry points: PASS
```

The full-repository Ruff run retains 43 pre-existing baseline findings outside
this scoped change set; it is not used as evidence of Pi readiness.
