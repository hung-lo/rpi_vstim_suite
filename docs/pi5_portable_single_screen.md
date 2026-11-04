# Portable single-screen Raspberry Pi 5

This profile runs the real Natural Images renderer through KMS on one HDMI
monitor. It needs no cameras, lick inputs, reward or suction hardware, USB
audio, or NVMe storage. A run is classified as a **real physical KMS display
test**; the fake-display integration tests are software checks only.

The profile is not calibrated for animal experiments. Before using visual
angle or retinotopy values, measure the monitor's physical width and height,
the viewing distance, and the relevant stimulus geometry. The example stores
zero for unmeasured physical dimensions and has no calibration ID.

## Install on the Pi 5

Use Raspberry Pi OS / Debian 13 (Trixie) with Python 3.13. Install the native
build and discovery tools:

~~~bash
sudo apt update
sudo apt install build-essential pkg-config libdrm-dev libwayland-dev libdrm-tests
~~~

The Debian Trixie [libdrm-tests file list](https://packages.debian.org/uk/trixie/arm64/libdrm-tests/filelist)
includes modetest, which reports the DRM connector mode list.
The KMS renderer links against libdrm and Wayland client support. The profile
does not need rpicam tools, lgpio, ffprobe, or sound-device packages.

From the checkout:

~~~bash
cd /home/pi/rpi_vstim_suite
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[images]'
make -C native/kms_display kms_probe
~~~

The user running VStim must be able to read the relevant /dev/dri/card device.
Do not change desktop services as part of installation.

## Discover the monitor

List every DRM connector and its kernel-reported supported modes without
changing display ownership or presenting a frame:

~~~bash
rpi-vstim hardware display-list --json
~~~

To preview the profile's actual single-screen selection:

~~~bash
rpi-vstim hardware display-probe \
  --config config/rigs/pi5_single_screen_display_only.example.toml --json
~~~

Automatic selection accepts exactly one connected HDMI connector. With more
than one, set stimulus_connector in the profile to the intended connector.
The preferred kernel mode is selected when present. If the kernel marks no
mode preferred, the deterministic fallback chooses the greatest pixel area,
then the highest supported refresh, then the mode dimensions/name. The
selected connector, resolution, and refresh are frozen before the scientific
plan is built. The KMS path checks that mode again and passes its dimensions
and nominal rate to the native renderer.

## DRM lease and direct ownership

The example requests **leased KMS**. The compositor must offer a DRM lease
for the chosen HDMI connector. A one-screen Pi may be using that same output
for its desktop, so exclusive stimulus presentation can conflict with the
desktop. A lease failure is reported as a display ownership problem.

VStim never changes ownership automatically, and it does not stop, kill, or
restart the compositor or display manager. For a standalone system where the
compositor has already released the output, direct ownership can be requested
explicitly:

~~~bash
rpi-vstim natural-images run \
  --mouse-id screen-test \
  --config config/rigs/pi5_single_screen_display_only.example.toml \
  --display-ownership direct \
  --output-root /home/pi/rpi_vstim_test_data \
  --image-count 5
~~~

Direct ownership requires exclusive DRM access. If the desktop owns the
monitor, first resolve that ownership manually using the Pi's normal
administration procedure. VStim reports the busy display and exits.

## Run a five-image display test

The example selects five images from the existing deterministic image
selection logic, uses a requested image duration of 500 ms, and adapts gray
and ITI durations to the chosen refresh rate:

~~~bash
cd /home/pi/rpi_vstim_suite
. .venv/bin/activate
rpi-vstim hardware display-list --json
rpi-vstim natural-images run \
  --mouse-id screen-test \
  --config config/rigs/pi5_single_screen_display_only.example.toml \
  --output-root /home/pi/rpi_vstim_test_data \
  --image-count 5
~~~

The startup report shows the resolved connector and mode, requested and
effective nominal image duration, output path, and disabled hardware. The run
does not require --cameras, --licks, --audio-coexistence, or --camera-preview.
The output root is a regular local directory on the microSD filesystem; the
existing production NVMe checks remain unchanged for the original production
path.

The renderer transforms images to the selected pixel resolution through the
existing image-preparation path. It does not assume a shared panel aspect
ratio or physical size. The configured photodiode patch and native KMS timing
trace remain enabled.

## Refresh-adaptive timing

The portable profile stores requested durations in milliseconds. VStim
converts each image, initial-gray, final-gray, and ITI duration to an integer
frame count using the selected mode's nominal refresh rate:

~~~text
frames = nearest integer(requested_ms * refresh_hz / 1000)
~~~

Exact half-frame ties round up. A nonzero request resolves to at least one
frame. The selected counts stay fixed for the session; visual transitions
occur on KMS page flips and are not scheduled with Python sleeps or wall-clock
millisecond timers.

natural_legacy_plain remains frame-based and strict. Its exact image, gray,
and ITI frame behavior and seeded image/ITI randomization are preserved. The
portable mode is opt-in through compatibility_profile =
"portable_display_only"; frame-based period fields are rejected in that
profile.

Each session records timing_provenance.json, including requested durations,
resolved frames, nominal durations, signed quantization errors, selected
display mode, and total planned frames. A duration that does not map exactly
to an integer frame count is not an exact millisecond presentation.

## Nominal and measured timing

The mode's nominal refresh and the planned frame counts describe the schedule.
They do not independently validate physical stimulus-onset timing. Inspect the
per-frame kernel page-flip trace in display_results.jsonl and the event
boundaries in events.jsonl. The native result records available kernel
timestamps, callback timestamps, missed-vblank counts, estimated dropped
frames, and whether the trace was truncated.

Kernel timestamps are useful display diagnostics, but are not a measurement of
the monitor's optical output. Use an independently acquired photodiode signal
to validate physical onset and offset timing.

## Physical validation checklist

- Confirm the selected connector and supported mode on the colleague's actual
  monitor with hardware display-list --json.
- Confirm that lease or explicitly selected direct ownership is available
  without VStim changing desktop services.
- Confirm that the session is labeled real_physical_kms_display_test and
  reports the selected width, height, refresh, and ownership mode.
- Check that the session output lands on /home/pi/rpi_vstim_test_data and
  that the filesystem has enough free space.
- Measure the monitor's physical width and height, viewing distance, and
  stimulus geometry before any visual-angle or retinotopy use.
- Check visible image transforms, gray levels, and the photodiode patch.
- Acquire the photodiode signal independently and compare optical onset and
  offset against the KMS page-flip trace.
- Review missing kernel timestamps, missed vblanks, dropped-frame estimates,
  and trace truncation in each session.
- Verify the Pi has no cameras, lick hardware, reward, suction, or USB audio
  connected if the intent is a display-only test.

Automated tests and fake-display runs validate software behavior; they do not
prove that physical KMS works on a particular Pi, compositor, or monitor.
