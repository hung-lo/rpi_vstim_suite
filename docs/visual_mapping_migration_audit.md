# Visual-mapping migration audit

Audit basis: unified repository `29fa6b78a14e6e7259c0c0ea729ed4e6f00a3647`
and frozen `rpi_visual_stimuli` commit
`6e1b2776e59c89127f9a6b56854096eb726990da`.

## Unified-repository architecture found

- The root `run_drifting_gratings.py` and `run_retinotopy.py` files are thin
  compatibility wrappers around `rpi_vstim.cli`; they are not protocol
  implementations.
- `src/rpi_vstim/protocols/{drifting_gratings,retinotopy}/__init__.py`
  already hold deterministic, frame-counted planners. `core.runtime` uses
  these for the hardware-independent simulation/virtual-run paths.
- The existing planners do not render pixels, create persistent render caches,
  or produce the retinotopy pixel-position table. The public `run` command is
  still a placeholder for real acquisition.
- The validated hardware path currently lives in
  `core.natural_image_demo`: it uses `KmsDisplayBackend.present_sequence`,
  `ProductionFrameRenderer`, `new_session`, `UnifiedEventStream`, and
  `LocalCameraSupervisor`. The lower-level components are reusable; the
  natural-image-specific orchestration is not a general protocol runner.
- TOML profiles load into typed `Config`; protocol parameters are nested under
  `[protocol]`. `SessionPlan` stores frame-quantized events. Current profile
  geometry is read from `DisplayConfig`; current Pi 5 geometry is not to be
  hard-coded in protocol modules.
- Simulation uses `FakeDisplayBackend` and `FakeLocalCameraService`. Existing
  planner tests include frozen-commit golden sequence fixtures.

## Frozen scientific behavior checked

| Historical source | Behavior to preserve | Destination | Intentionally excluded |
| --- | --- | --- | --- |
| Drifting-grating `config.py` / `sequence.py` | 8 orientations 0–157.5° in 22.5° steps; 80 per orientation; 0.5 s; 0.7 s + uniform [0, 0.5) s jitter; 2 Hz; 0.2 cycles/cm; contrast 1; mean 0.5; 3 s initial/final gray; shuffled balanced trials; one independent seeded jitter draw per trial | Existing `DriftingGratingSettings` / `SessionPlan`, extended with complete reproducible trial metadata | Old prompt/UI, old raw-cache lifecycle, old event/session writer |
| Drifting-grating `stimulus.py` | Stripe/bar orientation is `theta`; drift direction is `(theta - 90) mod 360`; phase advances by `2π·2 Hz·frame/configured_refresh`; spatial carrier uses screen-plane cm; full-screen sinusoid by default | Protocol-local renderer and cache; profile geometry and current KMS photodiode metadata | Old RPG display, old NumPy/RPG buffer ownership |
| Retinotopy `config.py`, `directions.py`, `sequence.py` | 20 s sweeps, 5 s gray after each sweep, 3 s initial/final gray, 15 Hz source positions, 0.10 bar-width fraction, 20 repeats/direction; fixed two-direction default, optional fixed/shuffled four-direction set | Existing `RetinotopySettings` / `SessionPlan`, direction data, and per-source-frame analysis table | Old GPIO TTL pulses, old operator prompts |
| Retinotopy `stimulus.py` | Adjacent black/white bars on configured gray; vertical pair for horizontal sweeps and horizontal pair for vertical sweeps; boundary travels from one off-screen edge to the other; reverse sweeps reverse the position order while retaining black-before-white spatial order | Protocol-local renderer/cache and `retinotopy_frame_plan.csv` | Old RPG display, old cache/session/storage and remote cameras |
| Historical `cache.py` / `runner.py` in both protocols | Pre-render and validate before playback; cache identity includes scientific/display/photodiode settings; contact sheets and run metadata | New packed-frame cache, preview commands, standard unified session/KMS/events/camera services | SSH camera topology, `/mnt/hd` output conventions, old RPG renderer, CSV-only event stream |
| Root runner scripts | Historical repository scripts delegated to protocol runners; unified-repo scripts now delegate to `rpi-vstim run` | Keep as compatibility wrappers; make `rpi-vstim drifting-gratings` and `rpi-vstim retinotopy` canonical | No old prompt-driven entrypoint |

The archived grating direction convention is intentionally preserved: a 0°
bar orientation is horizontal and drifts at 270°; a 90° bar orientation is
vertical and drifts at 0°. The old retinotopy geometry is linear in screen
pixels, not corrected for visual-angle velocity.
