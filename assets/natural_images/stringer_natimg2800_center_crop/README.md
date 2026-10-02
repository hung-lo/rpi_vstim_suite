# Stringer natural-image stimulus set

This is the actual 2,800-image natural-image stimulus set used by the legacy
Stringer/natural-image protocol. It was imported from the supplied
`stringer_natimg2800_center_crop_png.zip` archive; the archive's extra top-level
directory was removed during extraction.

- Count: 2,800 PNG files.
- Names: `natimg_center_0000.png` through `natimg_center_2799.png`.
- Source dimensions: 90 × 68 pixels.
- Source mode: 8-bit grayscale (`L`). The production preparer converts it to
  RGB888 before rendering.
- `MANIFEST.sha256`: sorted, deterministic SHA-256 entries for every image.

The repository's frozen source baseline identifies `vstim_natural` commit
`8a5f368c20344e25500cdfa6b272eccb673cad4a` as the natural-image reference and
`vstim_natural_img_reward` commit
`f64b56d0562b5c35aa64ffba34c29b1d7416bec1` as the reward-conditioning
reference. The unified compatibility profile preserves the recorded
presentation behavior: RGB conversion, centered aspect-preserving LANCZOS
crop, and gray value 127 for gray periods and transparent-image compositing.

No image license or redistribution permission was supplied with the archive,
and this repository does not establish either. Treat the corpus as an
internal/provided stimulus asset until its rights holder confirms otherwise.
