# Stringer natural-image stimulus set

This directory contains the 2,800-image natural-image stimulus set from the
dataset by Carsen Stringer, Marius Pachitariu, Matteo Carandini, and Kenneth
Harris, “Recordings of 10,000 neurons in visual cortex in response to 2,800
natural images.” The dataset was published by Janelia Research Campus on
Figshare.

- Dataset record: <https://janelia.figshare.com/articles/dataset/Recordings_of_ten_thousand_neurons_in_visual_cortex_in_response_to_2_800_natural_images/6845348>
- DOI: <https://doi.org/10.25378/janelia.6845348>
- Dataset citation: Stringer, Carsen; Pachitariu, Marius; Carandini, Matteo;
  Harris, Kenneth (2018). *Recordings of 10,000 neurons in visual cortex in
  response to 2,800 natural images*. Janelia Research Campus. Dataset.
  <https://doi.org/10.25378/janelia.6845348.v4>.

## License

These image assets are derived from material licensed under the [Creative
Commons Attribution-NonCommercial 4.0 International license (CC BY-NC
4.0)](https://creativecommons.org/licenses/by-nc/4.0/). That license permits
sharing and adaptation subject to its terms, including attribution and the
NonCommercial restriction. See [LICENSE.md](LICENSE.md) for the asset-level
notice.

The BSD-3-Clause license for original `rpi_vstim_suite` source code does not
apply to these natural-image assets. They remain subject to CC BY-NC 4.0. This
project does not claim ownership of the source images.

## Verified modifications and file identity

The source file `images_natimg2800_all.mat` is listed in the Figshare record
above. Its published MD5 (`4ccc523dffc948d3770dfa14bd51340f`) was verified
against the downloaded source file. The frozen legacy converter at
[`vstim_natural` commit
8a5f368](https://github.com/hung-lo/vstim_natural/blob/8a5f368c20344e25500cdfa6b272eccb673cad4a/convert_crop_middle_stringer_mat_to_png.py)
reads its `imgs` array (68 × 270 × 2,800), selects the center third of the
width (columns 90–179), and writes each 68 × 90 image as an 8-bit grayscale
PNG. The source array is `uint8`, so its pixel values are preserved; the
converter's normalization branch for other input types is not used. No
resizing, resampling, rotation, or transposition is applied in this conversion.
The PNG pixels in this directory were compared against all 2,800 corresponding
center-cropped arrays from the verified Figshare source file and matched
exactly. The imported archive's extra top-level directory was removed when
the files were placed in this directory; this does not change image pixels.
In short, these files have been modified from the source dataset by taking the
center third of each image and encoding those unchanged grayscale pixel values
as PNG.

At runtime, the display preparation path separately converts each source PNG
to RGB and applies the configured centered crop/resampling for the display.
That presentation transform does not alter the distributed PNG assets.

The files are named `natimg_center_0000.png` through
`natimg_center_2799.png`. `MANIFEST.sha256` records their SHA-256 hashes.

## Citation

When using these stimuli, cite both the original research publication and the
Figshare dataset:

The Figshare record identifies the research work as Stringer, Pachitariu et al.
(2018b), “High-dimensional geometry of population responses in visual cortex,”
bioRxiv, <https://doi.org/10.1101/374090>. The peer-reviewed version is:

Stringer, C., Pachitariu, M., Steinmetz, N., Carandini, M., & Harris, K. D.
(2019). High-dimensional geometry of population responses in visual cortex.
*Nature, 571*, 361–365. <https://doi.org/10.1038/s41586-019-1346-5>.

Stringer, Carsen; Pachitariu, Marius; Carandini, Matteo; Harris, Kenneth
(2018). *Recordings of 10,000 neurons in visual cortex in response to 2,800
natural images*. Janelia Research Campus, Figshare. Dataset DOI:
<https://doi.org/10.25378/janelia.6845348.v4>.
