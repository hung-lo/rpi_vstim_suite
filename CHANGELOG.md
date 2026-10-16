# Changelog

## Unreleased

- Added Phase 00 repository/package skeleton and source inventory.
- Added SSD-independent display-role configuration, strict DRM mode selection,
  read-only display-probe plumbing, storage-path inspection, and stable camera
  identity resolution. Production storage and hardware page-flip acceptance
  remain deferred.
- Added the direct-libdrm standalone KMS probe, bounded native test-pattern
  page flips, timing summaries, photodiode patch plumbing, and explicit native
  KMS CLI commands. Hardware modeset acceptance remains blocked by the active
  labwc DRM owner.
