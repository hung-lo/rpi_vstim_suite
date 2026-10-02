# Natural-image asset policy

Natural-image preparation is a producer-side operation. It must finish before
the native page-flip wait path consumes a frame; the native callback does not
open files, decode images, or perform Python work.

## Accepted inputs and identity

The supported source suffixes are `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, and
`.tiff`. Asset paths are relative to the configured asset root and cannot
escape it. Each decoded source is identified by its SHA-256 content hash;
prepared cache keys also include output dimensions, transform, and gray
background value.

The resolver records relative path, content hash, source dimensions/mode, and
byte size. Missing, unsupported, corrupt, and path-escaping assets fail with
explicit errors before a session can claim preparation success.

## Deterministic conversion

Inputs are converted to RGB888. Transparent images are composited over the
configured gray value. The default `fit_pad` policy preserves aspect ratio,
uses deterministic LANCZOS resampling, centers the image, and pads with gray.
`crop` uses a centered aspect-preserving crop; `stretch` resizes directly to
the target. Color management is not silently inferred: source images are
treated as the supplied RGB values and display calibration remains a later
hardware gate.

`AssetPreparer` retains only a bounded LRU of prepared RGB888 assets. The
natural-image frame source streams plan events and uses explicit immutable
asset keys; frame indices remain timing/provenance identifiers, never content
identity. The validated two-frame KMS raw-file path remains a smoke transport,
not the arbitrary natural-image sequence implementation.

Pillow is an optional `images` extra (`pip install -e '.[images]'`). A target
without Pillow reports an actionable preparation error rather than silently
changing image semantics.

The production corpus is in
`assets/natural_images/stringer_natimg2800_center_crop/`. Validate all 2,800
files, the static SHA manifest, the frozen crop transform, and the bounded
preparer with:

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_natural_image_assets.py \
  --asset-root assets/natural_images/stringer_natimg2800_center_crop \
  --width 1024 --height 600
```
