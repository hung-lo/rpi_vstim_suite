#!/usr/bin/env bash
set -euo pipefail

make -C native/kms_display clean all \
  CFLAGS="${CFLAGS:--O2 -Wall -Wextra -Wpedantic -Werror -std=c11}"
./native/kms_display/kms_frame_selftest
./native/kms_display/drm_lease_selftest
echo "portable native self-tests passed; DRM runtime was not opened"
