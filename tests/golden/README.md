# Golden tests

Fixed-seed software contracts live in `tests/unit/test_additional_protocols.py`
and `tests/unit/test_natural_images.py`. They cover the source-frozen schedule
shape and metadata without decoding images or generating display pixels.

Source baselines are recorded in `docs/source_baseline.md`; the reference
repositories remain read-only inputs. Hardware timing, display geometry, GPIO,
camera capture, and UDP delivery remain deferred hardware validation.
