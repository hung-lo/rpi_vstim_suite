# Source baseline

The four reference repositories were inspected at clean shallow clones on
2026-09-24. The old repositories were not edited and their Git histories were
not merged.

| Repository | Branch | Commit | Main role |
| --- | --- | --- | --- |
| `rpi_visual_stimuli` | `main` | `6e1b2776e59c89127f9a6b56854096eb726990da` | shared runtime, drifting gratings, retinotopy |
| `vstim_natural` | `main` | `8a5f368c20344e25500cdfa6b272eccb673cad4a` | natural-image presentation and camera variant |
| `vstim_natural_img_reward` | `master` | `f64b56d0562b5c35aa64ffba34c29b1d7416bec1` | reward conditioning, spout training, telemetry |
| `rpi_rig_monitor` | `main` | `70b80f25c12ac64d087ebeb78a22a091a0d03511` | separate UDP monitor consumer |

Reference tests were discovered in all four repositories. A test run was
attempted but could not start because `pytest` is not installed in the
inventory environment; no source test result is being represented as a pass.
See `source_baseline.json` for dependency and entrypoint details.

