# Codex Implementation Plan: Unified Raspberry Pi 5 Visual-Stimulus Suite

**Working repository name:** `rpi_vstim_suite`  
**Python package name:** `rpi_vstim`  
**Primary behavior-Pi deployment target:** `pi@10.42.84.10`  
**Target platform:** Raspberry Pi 5, Raspberry Pi OS Lite 64-bit, Python 3.13.x  
**Status:** Implementation blueprint only; no source repositories should be deleted or modified as part of the initial merge.
**Revision:** V2 — single experiment Pi 5 with two local cameras; removes the legacy second-camera-Pi/SSH-transfer architecture.

---

## 1. Objective

Create a new repository that replaces the experiment-side functionality currently spread across:

- `hung-lo/rpi_visual_stimuli`
- `hung-lo/vstim_natural`
- `hung-lo/vstim_natural_img_reward`

The new repository must run on Raspberry Pi 5 and expose one consistent runtime for:

1. Stringer natural-image presentation without reward.
2. Stringer natural-image presentation with local dual-camera recording on the same Pi 5.
3. Natural-image reward conditioning.
4. Lick-spout training.
5. Drifting gratings.
6. Retinotopy mapping.

It must also publish optional, best-effort, read-only telemetry to the separate `hung-lo/rpi_rig_monitor` repository. The monitor remains a separate repository and separate Raspberry Pi. It must never become a dependency of the experiment runtime.

The production experiment architecture uses **one Pi 5 for the complete experiment-side runtime**: visual stimulus presentation, lick acquisition, reward/suction/TTL control, local recording from two cameras, session logging, and telemetry publication. There is no second camera-acquisition Pi and no SSH-based camera-control or video-transfer path in the production design.

This is not a mechanical copy-and-paste merge. The present display dependency, `SjulsonLab/rpg`, is explicitly a Raspberry Pi 3/4 implementation built around legacy framebuffer, mailbox, `fbset`, `/dev/vcio`, and WiringPi interfaces. The Pi 5 production implementation therefore requires a new display abstraction and a Pi 5 KMS/DRM backend before any protocol can be declared production-ready.

---

## 2. High-level architectural decisions

Codex must follow these decisions unless a hardware proof demonstrates that one is impossible.

### 2.1 New repository, not merged Git histories

- Create a clean repository named `rpi_vstim_suite`.
- Do not combine the three old Git histories with subtree merges.
- Do not add the old repositories as runtime submodules.
- Record exact source commit hashes in `docs/source_baseline.json` and `docs/source_baseline.md`.
- Keep all three old repositories operational and unchanged until the new Pi 5 system completes hardware validation and several real sessions.

### 2.2 Source-of-truth mapping

Use the repositories as follows:

- **`rpi_visual_stimuli`**: starting point for the shared package structure, session handling, configuration, preflight, event logging, duration calculations, persistent cache concepts, operator status, camera wrapper, gray screen, GPIO abstraction ideas, drifting gratings, and retinotopy.
- **`vstim_natural`**: source of truth for the natural-image selection, reproducible scheduling, no-adjacent-repeat behavior, image conversion, natural-image timing, ITI generation, raw-image preparation, photodiode behavior, and the *session semantics* of the legacy camera workflow. Its remote-camera transport is reference-only and must not be carried into the Pi 5 production design.
- **`vstim_natural_img_reward`**: source of truth for reward-conditioning behavior, permanent mouse assignments, phase state, 8:3:1 block construction, 90% reward schedule, reward/suction/lick handling, spout training, water safeguards, behavior/QC summaries, session completion states, and nonblocking telemetry.
- **`rpi_rig_monitor`**: separate consumer of telemetry. Do not copy its Flask application into the experiment repository.

### 2.3 Python target

Use:

```toml
requires-python = ">=3.13,<3.14"
```

Do not pin the project to exactly Python 3.13.5. The user asked for Python 3.13.5 “or so”; the correct long-term target is the installed and validated Python 3.13 maintenance release on the Pi. Prefer the Raspberry Pi OS-provided Python 3.13 over compiling a custom interpreter.

### 2.4 Display target

- Production Pi 5 backend: direct Linux DRM/KMS, synchronized to page-flip/vblank events.
- Optional reference backend: existing `rpg` adapter for old Pi 4 validation only.
- Test backend: deterministic in-memory fake backend for CI and desktop development.
- Do not use pygame, an X11 window, a Wayland window, PsychoPy, browser rendering, or OpenCV windows as the production display path.
- Do not install the current `rpg` package with `sudo pip` on the Pi 5.
- Do not permit the current `rpg` installer to modify boot configuration or shell startup files.

### 2.5 GPIO target

- Use GPIO Zero with the explicit `LGPIOFactory`, or a thin direct `lgpio` adapter where timing or edge metadata requires it.
- Do not use WiringPi.
- Do not make `RPi.GPIO` a Pi 5 runtime dependency.
- Preserve a dedicated spawned hardware process for reward, suction, and lick capture.
- Monitoring, disk writes, terminal output, and camera work must never execute in the hardware timing process.

### 2.6 Monitor relationship

- Experiment controller sends UDP telemetry.
- Monitor receives and displays telemetry.
- No monitor-to-experiment command path.
- No acknowledgements, retries, blocking sockets, or session failure caused by monitor loss.
- No video stream, framebuffer capture, HDMI capture, or live camera stream to the monitor.
- Natural-image preview on the monitor uses a separately installed local image library and the image filename in telemetry.


### 2.7 Single-Pi dual-camera runtime model

The Pi 5 is the only experiment-side computer. It owns display, GPIO/lick/reward control, both cameras, logging, and telemetry. Design around isolation rather than a second machine.

Required process boundaries:

- **Main experiment/controller process:** protocol state, plan execution, display calls, session orchestration, and small in-memory event construction.
- **Dedicated GPIO worker process:** reward, suction, TTL, and lick-edge capture only. No camera, disk, JSON, terminal, or network work.
- **Two local camera capture workers/processes:** one independently supervised capture process per configured camera. Prefer direct camera-to-file pipelines rather than pulling frames through Python.
- **Telemetry worker process:** serialization/networking only.
- Optional post-session media verification/remux work occurs only after TASK/POST timing-critical activity has ended.

Rules:

- No SSH camera control in production.
- No camera file transfer between Pis in production.
- No live video transmission to `rpi_rig_monitor`.
- Camera workers must use bounded memory and stream directly to local session storage.
- Do not perform CPU-heavy transcoding, computer vision, or full-frame Python copies during TASK unless later hardware tests explicitly prove that timing is unaffected.
- A camera failure must not be able to leave reward/suction outputs unsafe or corrupt already-written stimulus/event data.
- Camera requirements are per camera: a protocol may require both, require one, or treat cameras as optional according to the resolved config.
- Stable camera identity must not depend only on `/dev/video0`/`/dev/video1`; use serial/device path/media topology or another stable identifier discovered during hardware audit.
- Because the audited Pi 5 has 2 GB RAM, camera buffering and image-stimulus caching must be bounded and measured under full simultaneous load.

---

## 3. Scope

### 3.1 Required protocol entry points

The unified CLI must support:

```bash
rpi-vstim run natural-images
rpi-vstim run reward-conditioning
rpi-vstim run spout-training
rpi-vstim run drifting-gratings
rpi-vstim run retinotopy
```

Camera recording is a shared local service rather than a separate implementation. Protocols enable configured camera IDs without changing their stimulus scheduler. For natural images, retain the familiar compatibility option while adding an explicit multi-camera form:

```bash
rpi-vstim run natural-images --camera          # enable the configured default camera set
rpi-vstim run natural-images --cameras all    # explicitly enable both configured cameras
rpi-vstim run natural-images --cameras face,behavior
```

The exact camera IDs/roles come from rig configuration; `face` and `behavior` are examples, not hard-coded production names.

The repository must also retain thin compatibility wrappers so the operator can use familiar commands during migration:

```text
run_stringer_vstim.py
run_stringer_vstim_cam.py
run_stringer_reward_conditioning.py
run_spout_training.py
run_drifting_gratings.py
run_retinotopy.py
```

Each wrapper must import the package CLI and provide only argument translation. No protocol logic may remain in the wrappers.

### 3.2 Required support commands

```bash
rpi-vstim doctor
rpi-vstim list-protocols
rpi-vstim assets convert-stringer
rpi-vstim assets verify
rpi-vstim cache build
rpi-vstim cache inspect
rpi-vstim hardware display-probe
rpi-vstim hardware display-test
rpi-vstim hardware gpio-test
rpi-vstim hardware reward-test
rpi-vstim telemetry demo
rpi-vstim telemetry benchmark
rpi-vstim session validate <session_directory>
rpi-vstim config import-legacy <legacy_json>
```

### 3.3 Explicit non-scope

- Basler caterpillar imaging is not part of this project.
- The daily data-sync repository is not merged into this project.
- The monitor web application is not embedded in this project.
- The first production release does not add browser-based experiment control.
- The first production release does not change the biological logic of the reward-conditioning task.
- Old assignment/state files are never reformatted in place.
- Old cache files do not need to be migrated; all caches are rebuildable.

---

## 4. Non-negotiable scientific and operational invariants

### 4.1 General runtime invariants

- Use monotonic clocks for intervals and deadlines.
- Record UTC nanosecond timestamps for cross-device correlation.
- Preserve photodiode output as the physical display ground truth.
- A software request time or page-flip timestamp is never described as physical stimulus onset.
- Random generators must be local objects with recorded seeds. Do not use process-global random state for protocol plans.
- The complete resolved configuration and all seeds must be saved before the first stimulus.
- Interrupts and exceptions must leave display and GPIO outputs in a safe state.
- An unavailable required camera may fail preflight/session startup, while an optional camera may degrade explicitly; neither case may corrupt completed stimulus data.
- Dual-camera recording must not measurably degrade display timing, lick capture, reward/suction timing, or telemetry parent-call latency.
- An unavailable monitor must not change protocol timing or session success.
- Experimental mode must refuse to run when display mode, refresh rate, GPIO ownership, state files, disk, or required calibrations are invalid.

### 4.2 Natural-image invariants

Preserve the validated behavior from `vstim_natural`:

- Reproducible image subset and sequence.
- No accidental adjacent repeats where the existing scheduler forbids them.
- 0.5 s image presentation.
- Jittered ITIs represented as integer monitor-refresh counts.
- Initial and final gray periods.
- Photodiode patch behavior.
- Selected-image table, plan, event logging, metadata, and local dual-camera archival behavior.

The current non-camera and camera runners differ in their final-ITI behavior. Do not silently erase this difference. Implement explicit compatibility profiles:

- `natural_legacy_plain`: includes the final ITI used by the plain runner.
- `natural_legacy_camera`: preserves the camera runner’s final transition behavior.

The compatibility wrappers select the corresponding profile. The unified CLI may later gain one canonical profile only after an explicit data-compatibility decision.

### 4.3 Reward-conditioning invariants

Preserve the production task behavior from `vstim_natural_img_reward`:

- Fourteen permanent natural images per mouse.
- Four high-, four medium-, and six low-exposure roles.
- Exact 8:3:1 presentation ratio per block.
- Ten blocks and 500 total trials in experimental mode.
- Acquisition and manually selected partial-reversal phases.
- Reversal never begins automatically.
- Fixed 90% reward probability on rewarded cues.
- Exactly 198 scheduled rewards and 22 scheduled omissions in the production 500-trial plan.
- Reward delivery is open-loop and independent of licking.
- Licks are measured, not used to gate reward.
- Behavioral target image duration is 1.5 s.
- Behavioral target reward boundary is 1.0 s after physical image onset.
- Suction remains scheduled on rewarded and omitted rewarded-cue trials according to the current protocol/configuration.
- PRE, TASK, and POST backgrounds and the explicit two-photon operator gate remain.
- Assignment, phase state, planned sequence, event log, trial summary, behavior summaries, QC, water accounting, and session completion state remain.
- Experimental block-count overrides remain forbidden outside simulation/development mode.

### 4.4 Spout-training invariants

Preserve:

- Gray-screen session.
- Open-loop reward delivery.
- Existing default reward pulse and volume configuration.
- Randomized 8-12 s training intervals unless overridden by a validated config.
- Suction scheduling.
- Lick capture and retrieval-success calculation.
- Maximum reward cap.
- Recent-20 criterion logic and explicit pass state.
- Automatic, manual, and disabled bait modes.
- Water accounting and manual bait safety limit.

### 4.5 Drifting-grating and retinotopy invariants

Preserve:

- Existing protocol configuration and deterministic sequence generation.
- Frame-based stimulus durations.
- Gray intervals.
- Visual-angle/geometry calculations.
- Photodiode patch behavior.
- Optional TTL behavior through the new GPIO abstraction.
- Persistent cache behavior.
- Preview-only, build-cache-only, dry-run, and test modes.
- Existing session event and manifest outputs.

---

## 5. First action: freeze and inventory the source baseline

Before implementing the new repository, Codex must create a source inventory.

### 5.1 Clone and record source state

Clone all four repositories into a sibling reference directory outside the new repository. For each repository, record:

- Remote URL.
- Default branch.
- Exact `git rev-parse HEAD` value.
- Dirty/clean state.
- Latest commit date.
- Python requirements.
- Entry points.
- Tests present and their pass/fail status.
- Configuration files.
- Persistent state directories.
- Session output files.
- Hardware dependencies.

Write the result to:

```text
docs/source_baseline.json
docs/source_baseline.md
```

### 5.2 Create a migration matrix

Create `docs/migration_matrix.md` with one row per meaningful source file/module. Required columns:

```text
source_repo
source_path
source_commit
destination_path
action
behavior_to_preserve
tests_required
status
```

Allowed `action` values:

- `port`
- `refactor`
- `replace_pi5_backend`
- `compatibility_wrapper`
- `reference_only`
- `retire_after_validation`

### 5.3 Freeze known-good reward calibration as a legacy profile

Document, but do not reuse blindly on Pi 5, the current Box151 profile:

```text
calibration_id = box151_photodiode_20ksps_50trial_60hz_v1
legacy_backend = rpg
segment_1_refreshes = 64
segment_2_refreshes = 24
stimulus_onset_compensation_sec = 0.095
```

Store this as a clearly labeled **legacy Pi 4/Box151 reference profile**. The Pi 5 KMS backend requires a new calibration ID and new physical measurements. The old `0.095` value must not become the default for an unmeasured Pi 5.

---

## 6. Read-only Pi 5 audit at `pi@10.42.84.10`

The first target-hardware interaction must be read-only. Do not install packages, edit boot files, change groups, or reboot during this audit.

Run a command equivalent to:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 pi@10.42.84.10 '
set -u
printf "== identity ==\n"
hostname
id
printf "== model ==\n"
tr -d "\000" </proc/device-tree/model 2>/dev/null || true
printf "\n== os ==\n"
cat /etc/os-release
printf "== python ==\n"
python3 --version
python3 -c "import sys; print(sys.executable); print(sys.version)"
printf "== kernel ==\n"
uname -a
printf "== firmware ==\n"
vcgencmd version 2>/dev/null || true
printf "== throttling ==\n"
vcgencmd get_throttled 2>/dev/null || true
vcgencmd measure_temp 2>/dev/null || true
printf "== drm devices ==\n"
ls -l /dev/dri 2>/dev/null || true
for p in /sys/class/drm/card*-*/status; do [ -e "$p" ] && echo "$p: $(cat "$p")"; done
for p in /sys/class/drm/card*-*/modes; do [ -e "$p" ] && echo "-- $p" && cat "$p"; done
printf "== framebuffer compatibility nodes ==\n"
ls -l /dev/fb* 2>/dev/null || true
printf "== gpio ==\n"
ls -l /dev/gpiochip* 2>/dev/null || true
printf "== mounts and disk ==\n"
findmnt /mnt/hd 2>/dev/null || true
df -hT / /mnt/hd 2>/dev/null || true
printf "== time sync ==\n"
timedatectl status 2>/dev/null || true
printf "== network ==\n"
ip -brief address
printf "== groups ==\n"
groups
'
```

Save the untouched output to `docs/hardware/pi5_initial_audit.txt`.

### 6.1 Audit gate

Do not label the target ready unless all of these are resolved:

- Hardware is actually a Raspberry Pi 5.
- OS is Raspberry Pi OS 64-bit based on Debian Trixie or a deliberately approved equivalent.
- `python3` is Python 3.13.x.
- `/mnt/hd` is mounted, writable, and has sufficient free space.
- The intended HDMI connector is connected.
- The exact intended mode and refresh rate are visible through DRM/KMS.
- The user `pi` can ultimately be granted non-root access to the needed DRM and GPIO devices.
- Time synchronization is active.
- No active thermal-throttling condition is reported.

If the Pi is on an older OS/Python combination, prefer a controlled OS reimage or upgrade. Do not solve this by compiling a private Python while retaining an obsolete graphics/GPIO stack.

---

## 7. Screen and rig-profile decision

The old repositories contain conflicting historical screen assumptions, including 1024x600 and 1280x720 configurations. Do not choose one by copying the first constant found.

Create named rig profiles. At minimum:

```text
config/rigs/pi5_ol7.example.toml
config/rigs/pi4_box151_legacy.example.toml
```

The current candidate for the OL7 profile is:

```toml
[display]
width_px = 1280
height_px = 720
refresh_hz = 60.0
physical_width_cm = 15.50
physical_height_cm = 8.72
eye_distance_cm = 16.0
```

Treat this as a candidate until the Pi 5’s actual connected display, EDID/mode list, screen measurement, image orientation, and eye geometry are verified. If the new Pi 5 uses the older 1024x600 display, create a distinct profile; do not overwrite the OL7 profile.

All baked/cache assets must include the rig-profile fingerprint. Assets generated for one resolution, photodiode geometry, pixel format, or refresh rate may not be reused for another.

---

## 8. Repository layout

Create this structure:

```text
rpi_vstim_suite/
├── README.md
├── IMPLEMENTATION_STATUS.md
├── CHANGELOG.md
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── .gitignore
├── .github/
│   └── workflows/
│       ├── tests.yml
│       └── lint.yml
├── config/
│   ├── system.example.toml
│   ├── rigs/
│   │   ├── pi5_ol7.example.toml
│   │   └── pi4_box151_legacy.example.toml
│   └── protocols/
│       ├── natural_images.example.toml
│       ├── reward_conditioning.example.toml
│       ├── spout_training.example.toml
│       ├── drifting_gratings.example.toml
│       └── retinotopy.example.toml
├── calibrations/
│   ├── README.md
│   └── box151_photodiode_20ksps_50trial_60hz_v1.reference.toml
├── docs/
│   ├── architecture.md
│   ├── source_baseline.md
│   ├── source_baseline.json
│   ├── migration_matrix.md
│   ├── data_format.md
│   ├── telemetry_protocol.md
│   ├── display_backend.md
│   ├── reward_timing.md
│   ├── camera_workflow.md
│   ├── deployment.md
│   ├── rollback.md
│   ├── hardware_acceptance.md
│   └── adr/
├── native/
│   └── kms_display/
│       ├── README.md
│       ├── kms_probe.c
│       ├── kms_display.c
│       ├── kms_display.h
│       └── python_module.c
├── scripts/
│   ├── audit_pi5.sh
│   ├── bootstrap_pi5.sh
│   ├── deploy_pi5.sh
│   ├── install_release.sh
│   ├── rollback_release.sh
│   ├── sync_monitor_assets.sh
│   └── collect_hardware_report.sh
├── src/
│   └── rpi_vstim/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── core/
│       │   ├── config.py
│       │   ├── lifecycle.py
│       │   ├── session.py
│       │   ├── provenance.py
│       │   ├── timestamps.py
│       │   ├── event_log.py
│       │   ├── manifests.py
│       │   ├── preflight.py
│       │   ├── operator_status.py
│       │   ├── progress.py
│       │   ├── duration.py
│       │   ├── cache.py
│       │   ├── assets.py
│       │   ├── camera.py
│       │   └── cleanup.py
│       ├── display/
│       │   ├── base.py
│       │   ├── models.py
│       │   ├── fake.py
│       │   ├── kms.py
│       │   ├── rpg_legacy.py
│       │   ├── frame_program.py
│       │   ├── photodiode.py
│       │   └── diagnostics.py
│       ├── hardware/
│       │   ├── base.py
│       │   ├── models.py
│       │   ├── simulated.py
│       │   ├── lgpio_backend.py
│       │   ├── worker.py
│       │   ├── client.py
│       │   ├── reward.py
│       │   ├── suction.py
│       │   ├── lick.py
│       │   └── ttl.py
│       ├── telemetry/
│       │   ├── publisher.py
│       │   ├── schema.py
│       │   ├── payloads.py
│       │   └── benchmark.py
│       ├── protocols/
│       │   ├── base.py
│       │   ├── natural_images/
│       │   ├── reward_conditioning/
│       │   ├── spout_training/
│       │   ├── drifting_gratings/
│       │   └── retinotopy/
│       ├── tools/
│       │   ├── convert_stringer.py
│       │   ├── verify_assets.py
│       │   ├── migrate_config.py
│       │   └── validate_session.py
│       └── validation/
│           ├── display.py
│           ├── gpio.py
│           ├── telemetry.py
│           └── session.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── golden/
│   ├── fixtures/
│   └── hardware/
├── run_stringer_vstim.py
├── run_stringer_vstim_cam.py
├── run_stringer_reward_conditioning.py
├── run_spout_training.py
├── run_drifting_gratings.py
└── run_retinotopy.py
```

Do not create one giant protocol runner. The current approximately 4,000-line reward runner must be decomposed by responsibility.

---

## 9. Configuration architecture

Use TOML as the canonical human-edited format because Python 3.13 includes `tomllib`.

### 9.1 Configuration layers

Resolve in this order:

1. Package defaults.
2. Rig profile.
3. Protocol profile.
4. Local machine config outside Git.
5. Explicit CLI overrides.

Save the fully resolved configuration as JSON in every session.

Recommended local paths:

```text
~/.config/rpi_vstim/system.toml
~/.config/rpi_vstim/rig.toml
~/.config/rpi_vstim/protocols/*.toml
```

Do not store writable state or machine-specific monitor addresses in Git. Camera configuration may include stable local device identifiers, but never secrets. The production camera path does not require SSH credentials.

### 9.2 Required system configuration sections

```toml
[paths]
output_root = "/mnt/hd"
cache_root = "/mnt/hd/vstim_cache"
asset_root = "/home/pi/stimulus_assets"
reward_state_root = "/mnt/hd/vstim_reward_assignments"

[display]
backend = "kms"
# Current verified Pi 5 mapping; revalidate if the final stimulus screen changes.
stimulus_connector = "HDMI-A-2"
preview_connector = "HDMI-A-1"
width_px = 1280
height_px = 720
refresh_hz = 60.0
pixel_format = "RGB565"
physical_width_cm = 15.50
physical_height_cm = 8.72
eye_distance_cm = 16.0

[photodiode]
enabled = true
corner = "bottom_right"
size_px = 50
on_value = 255
off_value = 0

[gpio]
backend = "lgpio"
chip = 0
reward_pin_bcm = 19
suction_pin_bcm = 25
lick_pin_bcm = 26

[cameras]
enabled_by_default = false
record_to_session = true
verify_output_growth = true

[[cameras.devices]]
id = "camera_1"
role = "face"
required = false
backend = "auto"
device = ""

[[cameras.devices]]
id = "camera_2"
role = "behavior"
required = false
backend = "auto"
device = ""

[telemetry]
enabled = false
required = false
host = ""
port = 5055

[session]
require_interactive_gate = true
```

The monitor host is intentionally empty in the example. The behavior Pi address `10.42.84.10` is not the monitor address and must not be reused as one.

### 9.3 Validation

Use frozen dataclasses and explicit validators. Do not rely on scattered module-level constants.

Experimental mode must reject:

- Missing monitor host when telemetry is enabled or marked required; the checked-in example remains disabled until the monitor Pi address is configured locally.
- Duplicate camera IDs or duplicate binding of two logical camera roles to the same physical device.
- Missing/unresolved stable device identity for a camera marked required in experimental mode.
- Unsupported camera backend/format/FPS combination once the hardware-specific rig profile is populated.
- Missing display calibration required by the selected protocol.
- Non-integer frame counts after duration conversion.
- Nonexistent asset or state directories.
- Writable assignment paths inside the code checkout.
- Same BCM pin assigned to multiple functions.
- Reward timing that overlaps suction in an unsafe way.
- Unsupported display mode/pixel format.
- Simulation flags combined with experimental mode.

### 9.4 Legacy config import

Implement:

```bash
rpi-vstim config import-legacy reward_conditioning_config.json
rpi-vstim config import-legacy spout_training_config.json
rpi-vstim config import-legacy config/system_config.json
```

The importer writes a new TOML file and a migration report. It never edits the legacy JSON file.

---

## 10. Common runtime lifecycle

Implement one `ExperimentRuntime` orchestration layer. Protocols supply plans and execute protocol-specific steps; the runtime supplies shared services.

### 10.1 Lifecycle states

Use explicit states:

```text
CREATED
CONFIGURED
PREFLIGHT
PREPARING
WAITING_FOR_2P
PRE
TASK
POST
CAMERA_CLEANUP
FINALIZING
COMPLETE
INCOMPLETE
INTERRUPTED
FAILED
CLEANUP_FAILED
```

Spout training can use protocol-specific phases under `TASK`, such as `BAIT`, `TRAINING`, and `PASSED`, while still reporting a common top-level lifecycle.

### 10.2 Session context

Define a frozen context containing at least:

```text
session_id
mouse_id
protocol_name
protocol_version
session_root
created_utc_ns
created_monotonic_ns
resolved_config
random_seeds
source_commit
host_provenance
```

### 10.3 Cleanup model

Use `contextlib.ExitStack` or equivalent ownership rules. Cleanup order must be explicit:

1. Stop accepting new protocol commands.
2. Force reward and suction outputs low.
3. Stop hardware worker.
4. Restore/close display backend.
5. Stop both camera workers, flush capture files, and record per-camera final states if enabled.
6. Perform only bounded local media verification needed before final status; defer expensive remux/transcode/repair until timing-critical work has ended.
7. Close telemetry with a bounded timeout.
8. Flush logs.
9. Atomically finalize manifest and status.

Cleanup failures must be recorded without hiding the primary exception.

---

## 11. Pi 5 display backend

This is the first hard implementation gate.

### 11.1 Why replacement is required

The existing `rpg` extension:

- Targets Pi 3 and Pi 4.
- Uses WiringPi.
- Opens legacy framebuffer and VideoCore mailbox devices.
- Calls `fbset`.
- Uses old framebuffer ioctls and buffer flipping.
- Installs with legacy `distutils` behavior.
- Attempts to edit boot and shell files during installation.

Do not treat successful import as proof that it is safe or correct on Pi 5.

### 11.2 Backend interface

Define a protocol-neutral interface similar to:

```python
class DisplayBackend(Protocol):
    def open(self, config: DisplayConfig) -> DisplayInfo: ...
    def validate_program(self, program: FrameProgram) -> None: ...
    def load(self, program: FrameProgram) -> LoadedProgram: ...
    def present(self, loaded: LoadedProgram, *, sequence_id: str) -> DisplayResult: ...
    def present_color(self, rgb: tuple[int, int, int], *, frames: int) -> DisplayResult: ...
    def unload(self, loaded: LoadedProgram) -> None: ...
    def close(self) -> None: ...
```

`DisplayResult` must contain:

```text
backend_name
connector
mode
pixel_format
sequence_id
requested_frame_count
completed_frame_count
first_page_flip_monotonic_ns
last_page_flip_monotonic_ns
first_page_flip_realtime_ns
mean_vblank_interval_us
std_vblank_interval_us
maximum_vblank_interval_us
missed_vblank_count
aborted
error
```

### 11.3 KMS/DRM proof of concept

Implement a standalone C probe before wrapping it for Python.

The probe must:

1. Open the configured `/dev/dri/card*` node.
2. Find the configured connected HDMI connector.
3. Enumerate modes.
4. Select the exact configured width, height, and refresh rate.
5. Enumerate usable CRTCs and planes.
6. Print supported plane formats.
7. Allocate two or three dumb buffers.
8. Fill alternating test patterns with a photodiode square.
9. Perform vblank-synchronized page flips using page-flip events.
10. Record page-flip sequence/timestamps.
11. Restore the original mode and console state on normal exit, error, SIGINT, and SIGTERM.

Use synchronous/vblank page flips. Do not use asynchronous page flips.

### 11.4 KMS backend implementation

After the standalone probe passes, expose it as a CPython extension or a tightly bounded native library wrapper.

Requirements:

- Link to `libdrm`.
- Release the Python GIL while waiting for and executing frame presentation.
- Use `CLOCK_MONOTONIC` or `CLOCK_MONOTONIC_RAW` consistently for frame intervals.
- Use DRM event timestamps/sequence numbers where available.
- Never allocate large buffers during an active presentation.
- Never read assets from disk during an active presentation.
- Never perform JSON, CSV, terminal, network, or camera work in the frame loop.
- Support an abort event/FD and reliable restoration.
- Reject mode changes after session preflight.
- Report dropped/missed vblanks explicitly.

### 11.5 Pixel format

Prefer `RGB565` when the selected plane supports it because this most closely matches the existing 16-bit presentation path. If the Pi 5 plane does not support it reliably, use `XRGB8888` and document the change.

The chosen format is part of the rig profile and cache key. Do not convert full frames in Python during a session.

### 11.6 Frame-program format

Do not make the new runtime depend on opaque legacy `rpg` cache files. Define a versioned `FrameProgram` cache format.

A cache object must contain:

```text
format_version
width_px
height_px
refresh_hz
pixel_format
frame_count
unique_frame_count
frame_repeat_schedule
source_hashes
generator_version
rig_profile_hash
photodiode_config_hash
binary_frame_file
```

Use memory-mapped, preconverted frame data. Support repeat schedules so a static image does not require ninety duplicate full-size frames.

Caches are disposable. Scientific session data and reward assignment/state files are not.

### 11.7 First-frame and milestone events

The renderer must be able to emit small local timing events without waiting for Python presentation completion. Use a nonblocking socketpair/event FD passed to the native layer.

Required event types:

```text
SEQUENCE_FIRST_FLIP
FRAME_MILESTONE
SEQUENCE_COMPLETE
SEQUENCE_ABORTED
```

Each event includes:

```text
sequence_id
frame_index
vblank_sequence
monotonic_ns
realtime_ns
```

This channel supports accurate reward scheduling and optional frame TTL without placing GPIO code inside the display backend.

### 11.8 Pi 5 display acceptance gate

Do not port all protocols onto a backend that has not passed:

- Exact intended mode and refresh rate.
- Correct image orientation and geometry.
- Correct photodiode-patch location and polarity.
- Correct gray, black, white, red, green, and blue test patterns.
- At least 10,000 consecutive vblank-synchronized presentations with zero missed/duplicated frame indices under normal load.
- Safe recovery from Ctrl-C and forced protocol exception.
- Repeated open/close without leaving the console or HDMI output unusable.
- No thermal-throttling flag during the stress test.
- Full timing report written to `docs/hardware/`.

If direct DRM/KMS fails after a documented prototype, write an architecture decision record before evaluating an SDL2 KMSDRM fallback. A desktop pygame path is not an acceptable fallback.

### 11.9 Legacy RPG adapter

Implement `RpgLegacyBackend` only to:

- Run source-equivalence tests on the old Pi 4.
- Compare old and new plans/assets.
- Preserve emergency rollback on old hardware.

It must be optional, imported lazily, and excluded from Pi 5 dependencies.

Do not copy upstream `rpg` C code into the new repository until its licensing/attribution requirements are documented. Prefer a clean DRM implementation based on public Linux/libdrm APIs.

---

## 12. GPIO and hardware-timing architecture

### 12.1 Pin ownership

All GPIO ownership belongs to one spawned hardware worker. The parent protocol process communicates through a local IPC channel.

The worker owns:

- Reward output.
- Suction output.
- Lick input and edge callbacks.
- Optional frame/segment TTL output.

The parent must not create duplicate GPIO Zero objects for the same pins.

### 12.2 Pi 5 backend

Instantiate GPIO Zero with an explicit `LGPIOFactory`, or use an internal direct `lgpio` layer if callback timestamps or scheduling require it.

The startup report must record:

```text
GPIO Zero version
lgpio version
selected gpiochip
pin factory
user/group permissions
configured pins
initial pin states
```

### 12.3 Hardware worker messages

Commands:

```text
SET_CONTEXT
ARM_STIMULUS
DELIVER_REWARD_NOW
SCHEDULE_REWARD
SCHEDULE_SUCTION
PULSE_TTL
SIMULATE_LICK
GET_STATUS
SHUTDOWN
```

Events:

```text
WORKER_READY
LICK_ONSET
LICK_OFFSET
REWARD_COMMAND_RECEIVED
REWARD_VALVE_ON
REWARD_VALVE_OFF
REWARD_COMPLETE
SUCTION_COMMAND_RECEIVED
SUCTION_ON
SUCTION_OFF
SUCTION_COMPLETE
TTL_ON
TTL_OFF
WORKER_ERROR
WORKER_STOPPED
```

Every command/event needs a command ID, sequence/trial context, monotonic timestamp, UTC timestamp, and pin number where relevant.

### 12.4 Reward scheduling from display onset

The final Pi 5 design must schedule reward and suction relative to a measured display event rather than assuming the old request-to-photodiode delay.

Recommended flow:

1. Parent sends `ARM_STIMULUS` to the hardware worker before presentation, including sequence ID and target delays.
2. The display backend emits `SEQUENCE_FIRST_FLIP` directly through a local nonblocking event channel.
3. The hardware worker or a dedicated timing coordinator receives the event and computes absolute monotonic deadlines.
4. Reward and suction use absolute deadlines.
5. The calibration profile provides the measured page-flip-to-physical-photodiode offset, if required.
6. The event log stores page flip, estimated physical onset, reward valve onset, suction onset, and photodiode/Intan calibration identity separately.

Fail closed: if a reward trial does not receive a valid matching first-flip event within its timeout, do not deliver a late unsynchronized reward. Abort the experimental task and preserve all logs.

### 12.5 Existing segmented reward display

During early equivalence testing, support a compatibility mode that reproduces the existing 1.0 s plus 0.5 s display segmentation. The final KMS production mode should be capable of one uninterrupted 1.5 s frame program with a milestone at the reward boundary, eliminating an unnecessary segment-boundary display gap.

Any transition from compatibility segmentation to continuous presentation requires photodiode/Intan validation and an explicit protocol/calibration version increment.

### 12.6 GPIO safety gates

Before an experimental run:

- Confirm all outputs initialize low.
- Confirm no pin collision.
- Confirm worker starts and reports ready.
- Confirm reward/suction durations and pulse counts are finite and within configured safety ranges.
- Confirm maximum session water cap.
- Confirm suction does not overlap an unsafe reward train.
- Confirm Ctrl-C and worker failure force outputs low.
- Confirm simulation mode is visibly labeled and cannot be confused with experimental mode.

---

## 13. Protocol package contract

Define a shared protocol interface. A protocol implementation should provide:

```python
class ExperimentProtocol(Protocol):
    name: str
    version: str

    def collect_settings(self, runtime: RuntimeServices) -> ProtocolSettings: ...
    def build_plan(self, settings: ProtocolSettings) -> ProtocolPlan: ...
    def preflight(self, plan: ProtocolPlan, runtime: RuntimeServices) -> PreflightReport: ...
    def prepare_assets(self, plan: ProtocolPlan, runtime: RuntimeServices) -> PreparedAssets: ...
    def run(self, plan: ProtocolPlan, assets: PreparedAssets, runtime: RuntimeServices) -> ProtocolResult: ...
    def finalize(self, result: ProtocolResult, runtime: RuntimeServices) -> None: ...
```

Plans must be immutable after they are written to disk. Runtime results are stored separately.

---

## 14. Natural-image protocol migration

### 14.1 Split the current monolith

Move responsibilities into:

```text
protocols/natural_images/config.py
protocols/natural_images/assets.py
protocols/natural_images/selection.py
protocols/natural_images/sequence.py
protocols/natural_images/cache.py
protocols/natural_images/outputs.py
protocols/natural_images/runner.py
```

### 14.2 Preserve plan behavior with golden tests

For fixed source images and fixed seeds, old and new code must agree on:

- Selected image IDs/files.
- Repeat counts.
- Order.
- No-adjacent-repeat constraints.
- ITI frame counts.
- Planned duration.
- Initial/final gray behavior.
- Final-ITI compatibility profile.

Create committed small synthetic image fixtures; do not put the full Stringer image dataset in Git.

### 14.3 Asset handling

- Port both Stringer MAT-to-PNG conversion tools into one command with explicit crop mode.
- Produce an asset manifest with SHA-256 hashes, dimensions, and source metadata.
- Verify images before session creation.
- Use basename-only telemetry for monitor preview, plus a content hash in session metadata.
- Never send image bytes through telemetry.

### 14.4 Camera mode

Natural-image camera mode uses the same protocol plan. Camera enablement changes lifecycle/camera operations, not the stimulus scheduler.

Keep the legacy wrapper behavior through the compatibility profile until explicitly unified.

---

## 15. Reward-conditioning migration

### 15.1 Decompose the runner

Create:

```text
protocols/reward_conditioning/config.py
protocols/reward_conditioning/assignment.py
protocols/reward_conditioning/state.py
protocols/reward_conditioning/sequence.py
protocols/reward_conditioning/timing.py
protocols/reward_conditioning/water.py
protocols/reward_conditioning/behavior.py
protocols/reward_conditioning/outputs.py
protocols/reward_conditioning/telemetry.py
protocols/reward_conditioning/runner.py
```

### 15.2 Assignment/state protection

The directory `/mnt/hd/vstim_reward_assignments` is backup-critical.

Rules:

- Never change files in place during migration.
- Before first use, create a timestamped recursive backup and SHA-256 inventory.
- Load legacy assignment/state schemas read-only.
- If a new schema is needed, write a new sibling file with an incremented schema version.
- Preserve mouse image identity, exposure role, reward trajectory, current contingency phase, and phase history exactly.
- Use file locking and atomic replacement.
- Refuse concurrent sessions for the same assignment directory.
- Add a `rpi-vstim reward-state inspect --mouse-id ...` command before any mutation command is considered.

### 15.3 Plan equivalence tests

For fixed assignment and sequence seeds, assert:

```text
14 unique images
10 blocks
50 trials per block
500 total trials
8 presentations per high image per block
3 presentations per medium image per block
1 presentation per low image per block
198 scheduled rewards
22 scheduled omissions
```

Test acquisition and partial reversal separately. Test that rollback requires the explicit override.

### 15.4 Timing profiles

Define:

- `box151_rpg_legacy_reference`: records the existing 64/24 and 0.095 s profile; old backend only.
- `pi5_kms_uncalibrated`: cannot run real reward sessions.
- `pi5_kms_<date>_<rig>_v1`: created only after physical validation.

A calibration profile records:

```text
backend
host hardware model
OS/kernel/firmware
connector/mode/refresh
pixel format
screen model
first-flip-to-photodiode statistics
programmed frame counts
reward target definition
reward valve timing statistics
suction timing statistics
sample count
measurement system
operator/date
source report paths
```

### 15.5 Water safeguards

Preserve current water accounting and cap enforcement. Keep delivered water and likely-consumed water labeled as distinct estimates. Do not label likely-consumed water as measured consumption.

### 15.6 Outputs

Preserve the existing filenames and columns wherever possible:

```text
session_manifest.json
<session>_event_log.csv
<session>_planned_sequence.csv
<session>_trial_summary.csv
<session>_image_assignment.csv
<session>_plan_summary.csv
<session>_behavior_summary.csv
<session>_behavior_summary.json
<session>_metadata.json
<session>_session_qc.json
<session>_lick_events.csv
raw_cache/
```

New fields may be appended. Do not rename or remove established fields in the first unified release.

---

## 16. Spout-training migration

Create:

```text
protocols/spout_training/config.py
protocols/spout_training/criterion.py
protocols/spout_training/schedule.py
protocols/spout_training/water.py
protocols/spout_training/outputs.py
protocols/spout_training/telemetry.py
protocols/spout_training/runner.py
```

Required tests:

- Interval generation remains within configured limits.
- Reward count never exceeds cap.
- Bait drops are excluded/included in the correct counters.
- Manual terminal mode restores terminal settings after every exit path.
- Criterion is not evaluated before the full window.
- Criterion pass occurs at the correct reward index.
- Lick windows and first-lick latency match legacy fixtures.
- Suction uses the same worker and safety handling as reward conditioning.

---

## 17. Drifting-grating migration

Port the current package modules rather than rewriting the protocol from memory.

Required components:

```text
protocols/drifting_gratings/config.py
protocols/drifting_gratings/sequence.py
protocols/drifting_gratings/generator.py
protocols/drifting_gratings/cache.py
protocols/drifting_gratings/events.py
protocols/drifting_gratings/telemetry.py
protocols/drifting_gratings/runner.py
```

The generator should produce backend-neutral frames/`FrameProgram` objects. It must not import KMS or legacy RPG directly.

Golden tests must compare:

- Condition list.
- Randomization/order.
- Orientation/direction conventions.
- Spatial and temporal frequency calculations.
- Frame count and phase progression.
- Gray timing.
- Expected total duration.
- Cache fingerprint.

Add rendered-frame tests for a small number of known grating conditions. Use numerical tolerances and image hashes after fixing pixel format and geometry.

---

## 18. Retinotopy migration

Required components:

```text
protocols/retinotopy/config.py
protocols/retinotopy/geometry.py
protocols/retinotopy/sequence.py
protocols/retinotopy/generator.py
protocols/retinotopy/cache.py
protocols/retinotopy/events.py
protocols/retinotopy/telemetry.py
protocols/retinotopy/runner.py
```

Preserve:

- Horizontal/vertical axis definitions.
- Sweep direction conventions.
- Bar/sweep geometry.
- Visual-angle calculations.
- Number of sweeps and inter-sweep gray.
- Photodiode behavior.
- Logged sweep metadata needed by the future two-photon retinotopy analysis pipeline.

Add a preview command that renders representative still frames to PNG on any computer without opening hardware display devices.

---

## 19. Local dual-camera subsystem

The legacy repositories contain overlapping `remote_camera_control.py` implementations. Review them for useful **lifecycle and recovery semantics only**: startup checks, output-growth verification, clean stop, conversion/recovery behavior, and clear final states. Do not preserve the SSH/remote-transfer architecture.

The Pi 5 production system records **two cameras locally on the same Pi that presents stimuli and controls behavior hardware**.

Recommended package boundary:

```text
src/rpi_vstim/camera/
├── base.py
├── models.py
├── local_capture.py
├── supervisor.py
├── diagnostics.py
└── verify.py
```

Keep the abstraction small. The implementation may supervise external capture tools (for example V4L2/FFmpeg or Raspberry Pi camera tools) when that avoids Python frame copies and gives more predictable resource use. Choose the concrete backend only after the Pi audit identifies the two real cameras and their supported modes.

### 19.1 Camera identity and configuration

Each configured camera must have:

```text
id
role
required
backend
stable_device_identifier
requested_width_px
requested_height_px
requested_fps
requested_pixel_format_or_codec
output_naming_policy
```

Do not bind production identity only to `/dev/videoN`; those numbers may change across reboots. Record enough udev/media/camera metadata to resolve the intended physical camera deterministically.

### 19.2 Process model

- Use one independently supervised local capture worker/process per camera.
- Camera workers do not own GPIO and do not execute protocol logic.
- The GPIO worker never performs camera operations.
- The display/frame loop never waits for camera I/O.
- Camera status enters the parent through a bounded IPC/status channel.
- Camera writes go directly to session storage with bounded buffering.
- Do not keep full-frame queues in Python memory.

### 19.3 Start/stop behavior

Before a camera-required session starts:

1. Resolve both configured physical devices by stable identity.
2. Confirm each required device is available and not already owned by another process.
3. Confirm the requested capture mode is supported.
4. Confirm session storage exists, has sufficient free space, and passes a conservative write-throughput preflight.
5. Start each camera independently.
6. Confirm each output file exists and grows within a bounded timeout.
7. Record camera start timestamps using both UTC and monotonic time.

On shutdown:

1. Request orderly stop for both camera workers.
2. Apply a bounded timeout, then escalate termination only if required.
3. Flush/close files and record size/duration/worker exit status for each camera.
4. Verify the local files sufficiently to distinguish `recorded`, `recorded_unverified`, `failed`, and `repair_needed`.
5. Never delete the only copy of a recording as part of automatic cleanup.

### 19.4 Media conversion and recovery

Legacy H.264-to-MP4 rescue logic is useful as a recovery reference, but conversion is now local.

- Prefer capturing directly into a robust/appropriate format when the hardware backend supports it without additional CPU cost.
- If H.264 elementary streams remain the most reliable capture format, record them during the session and remux/verify after timing-critical activity.
- Do not run expensive transcoding during TASK.
- Preserve the original capture if remux/repair fails.
- Any post-session repair state must be visible in `final_status.json` and the camera event log.

### 19.5 Dual-camera session outputs

Write a camera manifest containing per-camera:

```text
camera_id
role
stable_device_identifier
backend
negotiated_mode
start_utc_ns
start_monotonic_ns
stop_utc_ns
stop_monotonic_ns
output_path
bytes_written
reported_frames_if_available
dropped_frames_if_available
exit_status
verification_state
```

Use deterministic filenames such as:

```text
camera/<camera_id>/capture.h264
camera/<camera_id>/capture.mp4
camera/<camera_id>/events.jsonl
```

The exact extension may vary by backend, but the manifest is authoritative.

### 19.6 Performance rule

The dual-camera subsystem is not accepted merely because both files record. It must pass simultaneous-load tests with the real display, GPIO/lick worker, telemetry, and session logging. Any camera mode that causes missed vblanks, unsafe GPIO latency, excessive lick-event loss, memory pressure, thermal throttling, or storage stalls is rejected or reduced in resolution/FPS/codec load.

Camera operations must remain outside the display and GPIO timing paths.

---

## 20. Session data, cache, and provenance

### 20.1 Session directory

Keep the established direct layout under the configurable output root:

```text
/mnt/hd/<session_id>/
```

Do not insert a new `sessions/` level in the first release unless all downstream tools are updated.

### 20.2 Common files

Add these common files while retaining protocol-specific legacy outputs:

```text
session_manifest.json
resolved_config.json
provenance.json
preflight_report.json
final_status.json
cache_manifest.json
```

### 20.3 Provenance

Record:

```text
new repository commit
source baseline commits
Python version and executable
OS release
kernel
firmware
Pi model and serial-safe hardware identifier
installed dependency versions
display backend and native build ID
DRM connector/mode/pixel format
rig profile hash
protocol profile hash
calibration ID
asset manifest hash
all random seeds
monitor destination configuration without secrets
local camera stable identifiers, roles, negotiated capture modes, and capture backend/tool versions
```

### 20.4 Cache model

Use a persistent cache under `/mnt/hd/vstim_cache`.

Cache key includes:

```text
protocol/version
generator version
source asset hashes
rig profile hash
resolution
refresh rate
pixel format
photodiode settings
all visual parameters
```

Create the legacy `raw_cache/` session directory for compatibility. Populate it with a manifest and immutable hardlinks/symlinks to persistent cache objects when safe; fall back to copies if required. Analysis must not depend on the cache remaining present.

---

## 21. Telemetry architecture

### 21.1 Preserve the nonblocking design

Move the existing AF_UNIX `SOCK_DGRAM` handoff and spawned UDP worker into `telemetry/publisher.py`.

The experiment process may perform only:

1. Small in-memory payload construction.
2. One nonblocking local datagram send.

The worker owns:

- UTC packet timestamping.
- JSON serialization.
- UDP socket creation.
- Network errors.
- Packet transmission.

Full local buffers result in a dropped packet counter, not blocking.

### 21.2 Outer packet compatibility

Keep outer schema version 1 and message types:

```json
{
  "schema_version": 1,
  "type": "session | state | trial_complete",
  "protocol": "...",
  "session_id": "...",
  "timestamp_utc": "...",
  "...payload": "..."
}
```

Add a common payload schema version without breaking existing monitor parsing:

```text
telemetry_schema_version = 3
```

### 21.3 Common payload fields

Include flat compatibility fields plus structured protocol detail:

```text
sequence_number
mouse_id
protocol
protocol_version
session_id
phase
trial
trial_index
total_trials
block
block_index
total_blocks
image
stimulus_role
condition_label
stimulus_kind
stimulus_parameters
eta_sec
planned_finish_utc
camera_state
camera_states
qc_state
```

The monitor should ignore out-of-order packets using `sequence_number` within a session.

### 21.4 Protocol-specific trial payloads

Natural images:

```text
image_filename
image_id
repeat_index
planned_stim_frames
planned_iti_frames
```

Reward conditioning:

```text
contingency_phase
exposure_level
reward_trajectory
reward_eligible
reward_scheduled
reward_omission
reward_delivered
reward_contacted
anticipatory_lick
lick_times_sec
water counters
```

Spout training:

```text
training_reward_index
maximum_training_rewards
retrieval_success
recent_20_success_count
recent_20_success_fraction
criterion_evaluable
training_passed
water counters
recent lick state
```

Drifting gratings:

```text
orientation_deg
direction_deg
spatial_frequency_cpd
temporal_frequency_hz
contrast
stimulus_frames
iti_frames
```

Retinotopy:

```text
sweep_axis
sweep_direction
sweep_index
bar_width_deg
sweep_duration_frames
inter_sweep_frames
```

### 21.5 Telemetry timing rules

- Publish session setup once after session creation.
- Publish one-second heartbeats during WAITING, PRE, and POST.
- During TASK, publish state at safe trial/sweep boundaries.
- Publish one `trial_complete` packet after the trial record is complete.
- Do not publish per lick or per display frame over UDP.
- Licks are summarized in the next trial/state packet.
- Parent-side telemetry exceptions are swallowed and counted.
- Telemetry shutdown has a strict bounded timeout.

### 21.6 Telemetry benchmark gate

Retain and modernize the existing benchmark. Test with:

- Reachable monitor.
- Unreachable monitor.
- Worker killed.
- Full local socket buffer.
- Maximum allowed packet size.

Acceptance target on the behavior Pi:

```text
parent publish p95 <= 0.20 ms
parent publish p99 <= 0.50 ms
no unbounded call
no protocol exception from telemetry
```

Also run complete display timing tests with telemetry enabled and disabled and compare missed-vblank results.

---

## 22. Separate `rpi_rig_monitor` Pi 5 update

Create a separate branch/PR in `rpi_rig_monitor`, for example:

```text
feat/pi5-python313-generic-protocols
```

Do not merge this code into `rpi_vstim_suite`.

### 22.1 Runtime update

- Target Python `>=3.13,<3.14`.
- Replace old Python 3.7-era dependency pins with versions supporting Python 3.13.
- Convert to `pyproject.toml` if practical.
- Preserve UDP port 5055 and web port 8080 defaults.
- Add a systemd service example.
- Keep localhost/LAN-only deployment assumptions.

### 22.2 State model update

- Preserve all current reward and spout fields.
- Add common generic fields.
- Track `sequence_number` and ignore older packets for the active session.
- Reset protocol-specific state cleanly on session change.
- Keep bounded recent-trial history.
- Preserve LIVE/STALE behavior.

### 22.3 Dashboard update

Display protocol-appropriate condition summaries:

- Natural-image filename/preview and trial/ETA.
- Reward/omission/delivery/contact/lick labels.
- Spout criterion/water/recent lick status.
- Grating orientation/direction/frequencies.
- Retinotopy axis/direction/sweep progress.

Do not attempt a framebuffer or camera preview. Natural-image preview uses only files already installed on the monitor Pi.

### 22.4 Contract tests

Add packet fixtures from every protocol and test:

- Session reset.
- Out-of-order packet rejection.
- Unknown extra fields.
- Malformed packets.
- Reward labels.
- Generic condition labels.
- Missing local preview image.
- Stale transition.
- Monitor restart while experiment continues.

---

## 23. Pi 5 bootstrap and dependency policy

### 23.1 Base OS

Target Raspberry Pi OS Lite 64-bit based on Debian Trixie. Lite avoids a desktop compositor competing for DRM master.

### 23.2 Bootstrap script

`scripts/bootstrap_pi5.sh` must:

- Detect Pi model and OS before changing anything.
- Refuse unsupported OS/model unless an override is supplied.
- Use `apt`, not `sudo pip`, for system libraries.
- Install/check packages equivalent to:

```text
python3
python3-venv
python3-dev
python3-gpiozero
python3-lgpio
build-essential
pkg-config
libdrm-dev
libdrm-tests
edid-decode
ffmpeg
rsync
openssh-client
git
```

- Verify package availability before installation because exact Debian package names can differ.
- Add `pi` to only the required device groups, typically `video`, `render`, and `gpio`.
- Print that a logout/reboot may be required after group changes.
- Never modify boot configuration without a separate explicit command and backup.
- Never modify `.bashrc`.

### 23.3 Virtual environment

Use:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

`--system-site-packages` is allowed so the venv can use apt-installed Pi GPIO bindings. Record all imported versions in provenance.

### 23.4 Python dependencies

Keep the experiment dependency set small. Expected categories:

- Pillow.
- NumPy.
- GPIO Zero.
- Standard-library TOML reader.
- Native display extension.

Development dependencies:

- pytest.
- pytest-timeout.
- coverage.
- ruff.
- mypy or pyright if used consistently.

Do not add a web framework to the experiment repository.

### 23.5 Controlled system updates

After hardware validation, record kernel, firmware, Mesa/libdrm, and GPIO package versions. OS updates must be staged and the hardware acceptance suite rerun before experiments resume. Do not rely on unattended platform changes for a timing-critical rig.

---

## 24. Testing strategy

### 24.1 Unit tests

Cover:

- Configuration parsing/validation.
- Duration-to-frame conversion.
- Session naming.
- Atomic JSON writing.
- Assignment and state locking.
- Seed handling.
- Sequence generation.
- Water accounting.
- Behavior metrics.
- Telemetry payloads.
- Camera state derivation.
- Final status derivation.

### 24.2 Golden/contract tests against old repositories

Create fixtures from the frozen source commits and assert old/new equivalence for:

- Natural-image selection and sequence.
- Natural-image ITIs and final-ITI profiles.
- Reward image assignment.
- Reward acquisition/reversal plans.
- Reward counts and omissions.
- Behavior metric windows.
- Spout criterion logic.
- Grating condition order and frame counts.
- Retinotopy sweep order and frame counts.
- Existing output column names.
- Existing telemetry reward fields.

Where the new display backend necessarily changes low-level timing, compare the protocol plan, not legacy software-request timestamps.

### 24.3 Integration tests with fake hardware

The fake display and fake GPIO worker must support deterministic virtual monotonic time. Run complete short sessions for every protocol without sleeping in real time.

Test:

- Normal completion.
- Ctrl-C at each lifecycle phase.
- Display failure.
- Hardware worker failure.
- Monitor absent.
- Camera unavailable.
- Disk-full simulation.
- Corrupt cache.
- Corrupt assignment file.
- Stale lock recovery.
- Finalization failure.

### 24.4 Pi 5 hardware tests

Mark with a dedicated pytest marker and never run them in normal CI:

```bash
pytest -m hardware
```

Hardware tests require explicit flags for water delivery. Default hardware tests must not actuate reward or suction.

### 24.5 CI

Normal CI runs on Python 3.13 with fake display/GPIO only. It must not import Pi-only modules at collection time.

Required checks:

```text
ruff check
unit tests
contract tests
integration tests
build wheel/source distribution
import CLI
```

---

## 25. Hardware validation program

### 25.1 Display-only validation

Run, save, and review:

1. Mode/connector probe.
2. Solid-color test.
3. Photodiode square polarity test.
4. 10,000-frame alternating pattern.
5. Static natural image for known frame counts.
6. Representative drifting gratings.
7. Representative retinotopy sweeps.
8. Ctrl-C and exception recovery.
9. Telemetry on/off stress comparison.
10. Thermal/throttling report.

### 25.2 Physical photodiode validation

Use Intan/photodiode recordings to measure:

- Software request to page flip.
- Page flip to physical photodiode onset.
- Physical stimulus duration.
- Segment/milestone position.
- ITI duration.
- Trial-to-trial jitter.

Do not copy the Box151 compensation into the Pi 5 profile. Derive and version a new profile.

### 25.3 Reward/suction validation

With no mouse and controlled water collection:

- Validate reward pulse train.
- Validate volume calibration.
- Validate reward onset relative to physical photodiode onset.
- Validate suction onset/duration.
- Validate rewarded and omitted cue paths.
- Validate lick input using a controlled test signal/manual contact.
- Validate session water cap.
- Validate failure behavior when onset event is absent.

Use at least the same scale as the prior 50-trial display calibration. Report median, p95, range, and outliers. Physical timing should remain within one display refresh of the approved behavioral target unless a stricter protocol-specific threshold is defined in `docs/hardware_acceptance.md`.

### 25.4 Dual-camera validation

First identify the real camera stack and stable identities using read-only tools such as `v4l2-ctl --list-devices`, `udevadm info`, `lsusb -t`, media-controller inspection, and Raspberry Pi camera enumeration commands when applicable. Do not assume the many `/dev/video*` nodes correspond one-to-one with the two physical cameras.

Validate each camera alone and both simultaneously:

- Stable device resolution across reboot/replug where applicable.
- Requested versus negotiated resolution/FPS/format.
- Start/stop and bounded shutdown.
- Output-growth confirmation.
- Local file verification.
- Conversion/remux retry/recovery when used.
- Capture-process crash handling.
- One-camera failure while the other continues.
- Disk-full/low-space preflight behavior.
- No deletion of the only local capture after verification failure.
- Per-camera timestamp/manifest completeness.
- Dropped-frame reporting when the backend exposes it.

Then run an integrated single-Pi stress test with:

- Both cameras recording.
- KMS display presenting a representative high-load frame program.
- GPIO worker active with simulated/manual lick edges and reward outputs disabled or safely instrumented.
- Telemetry enabled and disabled in comparison runs.
- Normal session logging to the target storage.

Record CPU load, RAM/swap, disk throughput/latency, temperature/throttling, display missed-vblank metrics, lick-event integrity, camera drops, and telemetry publish latency. The selected two-camera mode is accepted only if it does not measurably compromise experimental timing/safety.

### 25.5 Monitor validation

- Monitor unreachable at session start.
- Monitor disappears during TASK.
- Monitor returns during session.
- Packet loss/reordering.
- All protocol displays.
- Missing preview assets.
- No timing degradation on the behavior Pi.

---

## 26. Deployment and rollback

### 26.1 Deployment target

Use `pi@10.42.84.10` only in deployment configuration/scripts, not protocol code.

Because `10.42.84.10` is a private network address, deployment must first verify that the development machine has a route to the lab network/VPN. A failed SSH preflight is not a code failure.

### 26.2 Versioned releases

Deploy into versioned directories:

```text
/home/pi/rpi_vstim_suite/releases/<git_commit>/
/home/pi/rpi_vstim_suite/current -> releases/<git_commit>/
/home/pi/.config/rpi_vstim/
/mnt/hd/vstim_cache/
/mnt/hd/vstim_reward_assignments/
/mnt/hd/<session_id>/
```

Code releases are replaceable. Config, cache, state, assets, and session data stay outside the release directory.

### 26.3 Deployment script behavior

`scripts/deploy_pi5.sh` must:

1. Verify SSH host key and target identity.
2. Run read-only target preflight.
3. Refuse dirty/uncommitted local deployment unless overridden.
4. Build/test locally.
5. Copy to a new release directory without deleting data paths.
6. Create/update the venv.
7. Build the native extension.
8. Run `rpi-vstim doctor` and non-water smoke tests.
9. Switch the `current` symlink only after success.
10. Print the rollback command.

Do not use a broad `rsync --delete` against `/home/pi` or `/mnt/hd`.

### 26.4 Rollback

Rollback switches `current` to the previous validated release and reruns `doctor`. State and session data are untouched.

Keep the old Pi 4 repositories/runners available until the unified Pi 5 system has completed:

- Display acceptance.
- Reward no-mouse validation.
- One non-reward real session.
- At least three successful reward sessions without unexplained timing/QC regressions.

---

## 27. Implementation phases and gates

Codex must implement in this order. Do not mark a later hardware-dependent phase complete because unit tests pass.

### Phase 0 - Source freeze and migration inventory

- [ ] Create source baseline files.
- [ ] Create migration matrix.
- [ ] Record current tests and outputs.
- [ ] Record known-good Box151 calibration as reference only.
- [ ] Back up and hash reward assignment/state files before any target use.

**Gate 0:** Every source behavior has an owner/destination or is explicitly reference-only.

### Phase 1 - Repository skeleton and fake runtime

- [ ] Create package/CLI/repository structure.
- [ ] Add Python 3.13 CI.
- [ ] Add TOML config loader and validators.
- [ ] Add common lifecycle/session/provenance/output services.
- [ ] Add fake display and fake hardware worker.
- [ ] Add compatibility wrappers.
- [ ] Add `rpi-vstim doctor` skeleton.

**Gate 1:** A fully simulated minimal session can run and finalize through the package CLI.

### Phase 2 - Pi 5 audit and bootstrap

- [ ] Run read-only SSH audit at `pi@10.42.84.10`.
- [ ] Resolve OS/Python/mount/permission issues.
- [ ] Identify both physical cameras and map stable identities, supported formats, FPS/resolutions, and USB/CSI/media topology.
- [ ] Measure target storage free space and baseline sequential write throughput suitable for two concurrent camera streams.
- [ ] Create and review the actual rig profile.
- [ ] Install dependencies using bootstrap script.
- [ ] Confirm no runtime requires root.

**Gate 2:** Target report is complete and Python 3.13.x, DRM, GPIO, both cameras, storage, and time sync are ready for backend implementation.

### Phase 3 - KMS/DRM display proof and backend

- [ ] Implement standalone KMS probe.
- [ ] Run connector/mode/plane/pixel-format discovery.
- [ ] Implement safe page-flip test.
- [ ] Implement Python backend wrapper.
- [ ] Implement frame-program cache format.
- [ ] Implement display-event channel.
- [ ] Pass 10,000-frame stress/recovery tests.

**Gate 3:** Direct KMS backend passes engineering acceptance on the actual display.

### Phase 4 - Natural images and local dual-camera subsystem

- [ ] Port converter and asset verification.
- [ ] Port selection/sequence/ITI behavior.
- [ ] Add both legacy final-ITI profiles.
- [ ] Port event/metadata outputs.
- [ ] Replace the legacy remote camera transport with the local dual-camera supervisor/workers.
- [ ] Add stable device resolution and per-camera manifests.
- [ ] Keep capture streaming/buffering bounded and outside Python frame queues.
- [ ] Pass golden plan tests.
- [ ] Run no-camera, each-camera-only, and both-camera hardware sessions without a mouse.
- [ ] Run display timing comparison with cameras off versus both cameras on.

**Gate 4:** Natural-image presentation matches plan and physical photodiode timing while both local cameras can record concurrently without unacceptable display, memory, storage, or thermal impact.

### Phase 5 - Pi 5 GPIO worker, spout training, and integrated contention test

- [ ] Port worker to explicit lgpio backend.
- [ ] Add safe IPC/event model.
- [ ] Port spout training.
- [ ] Validate no-water GPIO behavior.
- [ ] Validate controlled reward/suction/lick behavior.
- [ ] Pass criterion/water/accounting tests.
- [ ] Stress the GPIO/lick worker while both cameras record and the KMS display runs.
- [ ] Verify camera workers cannot block reward/suction cleanup or cause lick-event loss.

**Gate 5:** GPIO safety and spout-training acceptance pass under the same-Pi dual-camera load, not only with cameras disabled.

### Phase 6 - Reward conditioning

- [ ] Port assignment/state code without in-place migration.
- [ ] Port sequence, water, behavior, QC, and outputs.
- [ ] Add compatibility segmented display mode.
- [ ] Add continuous KMS milestone mode behind calibration.
- [ ] Build new Pi 5 timing calibration.
- [ ] Run no-mouse 50+ trial validation with the production dual-camera mode enabled as well as a camera-off comparison run.
- [ ] Verify acquisition and reversal plans.

**Gate 6:** Reward timing and safety are physically validated and a versioned Pi 5 calibration profile exists.

### Phase 7 - Drifting gratings and retinotopy

- [ ] Port generators to backend-neutral frame programs.
- [ ] Port caches, sequence, logging, preview, and test modes.
- [ ] Pass golden plan/render tests.
- [ ] Run photodiode validation for representative conditions.

**Gate 7:** Both protocols pass frame, geometry, sequence, and physical display checks.

### Phase 8 - Unified telemetry

- [ ] Move nonblocking publisher into shared package.
- [ ] Add generic packet schema and protocol adapters.
- [ ] Add sequence numbers.
- [ ] Pass telemetry benchmarks.
- [ ] Confirm monitor loss never changes session success/timing.

**Gate 8:** All protocols emit contract-tested telemetry with bounded parent overhead.

### Phase 9 - Monitor Pi 5 companion PR

- [ ] Update monitor to Python 3.13-compatible dependencies.
- [ ] Add generic state/UI fields.
- [ ] Preserve reward/spout UI behavior.
- [ ] Add packet fixtures for every protocol.
- [ ] Deploy to the Pi 5 monitor and run restart/stale tests.

**Gate 9:** Monitor displays all protocols while remaining read-only and optional.

### Phase 10 - Full-system validation and cutover

- [ ] Run complete hardware acceptance suite.
- [ ] Run one real non-reward session.
- [ ] Run staged reward sessions with QC review.
- [ ] Verify analysis pipelines still read expected outputs.
- [ ] Document rollback.
- [ ] Mark old repositories as legacy only after successful cutover; do not delete them.

**Gate 10:** User approves production cutover.

---

## 28. Definition of done

The new system is complete only when all are true:

- One new repository exposes all six required protocol workflows.
- Production behavior Pi is a Raspberry Pi 5 running validated Python 3.13.x.
- Production display uses a validated KMS/DRM backend, not legacy Pi 3/4 framebuffer/mailbox code.
- GPIO uses a validated Pi 5-compatible lgpio path.
- Natural-image plans match the old implementation for fixed seeds and selected compatibility profile.
- Reward plans match exact established counts and assignments.
- Reward/suction timing has a new Pi 5 physical calibration.
- Spout-training criterion and water safeguards pass tests.
- Drifting gratings and retinotopy pass geometry/frame tests.
- Both local cameras can record concurrently on the experiment Pi; their data and manifests are verified and safely retained.
- Full dual-camera recording does not cause unacceptable display timing errors, lick loss, reward/suction timing degradation, memory pressure, disk stalls, or thermal throttling.
- Existing important output filenames and columns remain usable.
- Assignment/state data was not lost or mutated unsafely.
- Telemetry is nonblocking, optional, and protocol-neutral.
- `rpi_rig_monitor` runs on its Pi 5/Python 3.13 environment and understands all protocols.
- Monitor unavailability has no measurable effect on display/GPIO timing.
- Every session records complete provenance.
- Deployment and rollback scripts are tested.
- Hardware acceptance reports and calibration profiles are committed where appropriate, with machine-local secrets/data excluded.

---

## 29. Prohibited shortcuts

Codex must not:

- Install current `rpg` with `sudo pip` on the Pi 5 and declare the port complete.
- Depend on `/dev/fb0`, `/dev/vcio`, WiringPi, or `fbset` as the Pi 5 production path.
- Use pygame or a desktop window as an unvalidated replacement.
- Hardcode the monitor address to the behavior Pi address.
- Put monitor networking in the display or GPIO timing loop.
- Send image or video data through telemetry.
- Add monitor control commands.
- Copy all old scripts into one larger monolith.
- Change reward contingencies, counts, timing targets, or state identity while refactoring.
- Convert assignment/state files in place.
- Delete old repositories, source data, assignments, or session outputs.
- Run reward/suction hardware tests without an explicit water-actuation flag.
- Run experimental reward conditioning with an uncalibrated Pi 5 display profile.
- Hide cleanup or camera failures behind a generic `complete` status.
- Reintroduce a second/remote camera Pi, SSH camera control, or automatic cross-Pi video transfer into the production path.
- Hard-code camera identity to `/dev/video0` and `/dev/video1`.
- Pull full camera frames through Python or run CPU-heavy video transcoding during TASK without a saved hardware timing/resource acceptance report.
- Let a camera worker own reward/suction/lick GPIO or run inside the GPIO timing process.
- Treat software timestamps as physical onset without calibration.
- Modify `/boot/firmware/config.txt`, kernel command line, or system groups without backup and an explicit logged step.

---

## 30. Required documentation deliverables

Codex must keep these current during implementation:

- `IMPLEMENTATION_STATUS.md`: phase checklist and current blockers.
- `docs/architecture.md`: final component diagram and process boundaries.
- `docs/display_backend.md`: DRM/KMS design and recovery behavior.
- `docs/reward_timing.md`: timing references, event flow, and calibration semantics.
- `docs/data_format.md`: common and protocol-specific outputs.
- `docs/telemetry_protocol.md`: packet schema and examples.
- `docs/camera_workflow.md`: local two-camera identity, process model, outputs, success/failure states, and recovery.
- `docs/resource_budget.md`: simultaneous display/GPIO/dual-camera/storage/telemetry load measurements and accepted operating envelope.
- `docs/deployment.md`: clean install and update.
- `docs/rollback.md`: code and hardware rollback.
- `docs/hardware_acceptance.md`: exact commands, measurements, acceptance results, and sign-off.
- `THIRD_PARTY_NOTICES.md`: copied/reused code and license attribution.

---

## 31. Codex execution rules

1. Work in small, reviewable commits aligned to the phases above.
2. Start with Phase 0 and Phase 1; do not begin by rewriting the reward runner.
3. Run all relevant tests after each commit.
4. Keep hardware imports lazy so desktop/CI tests work.
5. Preserve source behavior first; simplify only after equivalence tests exist.
6. When old repositories disagree, encode named compatibility profiles rather than silently choosing one.
7. Record all deliberate behavior changes in an ADR and changelog.
8. Never perform destructive remote actions automatically.
9. Remote deployment/audit commands to the experiment Pi begin with identity and read-only preflight checks; camera recording itself is local and does not use SSH.
10. Physical hardware gates require saved reports; a successful command exit is not sufficient evidence.
11. Do not mark the implementation production-ready while the display or reward calibration is pending.
12. Maintain the old Pi 4 path as a rollback reference until the user explicitly approves retirement.

---

## 32. Initial Codex task

Begin with the following bounded task:

> Create the `rpi_vstim_suite` repository skeleton, `pyproject.toml`, package CLI, configuration dataclasses/validation, fake display backend, simulated hardware worker, common session/lifecycle/provenance outputs, compatibility-wrapper stubs, Python 3.13 CI, source-baseline templates, migration-matrix template, and `IMPLEMENTATION_STATUS.md`. Do not yet copy protocol monoliths or modify the Pi. Then inventory the four source repositories at their current commits and fill the baseline/migration files. Run tests and commit this as Phase 0/1 groundwork.

After that commit, perform the read-only Pi 5 audit, including explicit identification of both local cameras and their stable device/mode information, then start the standalone KMS display probe. The KMS gate is the first hardware-critical milestone; dual-camera resource acceptance follows once the display backend exists.
