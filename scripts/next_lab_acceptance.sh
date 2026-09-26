#!/usr/bin/env bash
set -euo pipefail

mode=dry-run
if [[ "${1:-}" == "--write-heavy" ]]; then
  mode=write-heavy
elif [[ "${1:-}" != "" && "${1:-}" != "--dry-run" ]]; then
  echo "usage: $0 [--dry-run|--write-heavy]" >&2
  exit 2
fi

cat <<'EOF'
Next-lab acceptance is Pi-side preparation only. Do not run it from the Mac.
Hardware assignments: HDMI-A-2 / connector 42 = stimulus;
HDMI-A-1 / connector 33 = camera monitor.

Safe checks:
  python3 --version
  make -C native/kms_display clean all
  rpi-vstim preflight --config /path/to/production.toml --json
  rpi-vstim hardware display-probe --config /path/to/production.toml --json
  rpi-vstim hardware kms-probe --config /path/to/production.toml --lease --json
  rpi-vstim hardware kms-render-smoke --config /path/to/production.toml --frames 300 --lease --json
  v4l2-ctl --list-devices
  findmnt --target /mnt/experiment-ssd
  rpi-vstim inspect-session /mnt/experiment-ssd/<session-id> --json

Never format disks, change fstab, reboot, touch GPIO, or deliver reward.
Photodiode acceptance remains deferred until a sensor is available.
EOF

if [[ "$mode" == "dry-run" ]]; then
  cat <<'EOF'
Write-heavy stages are withheld. Re-run on the Pi with --write-heavy only
after recording the SSD identity and confirming the configured root is not the
SD card, /, or a temporary directory:
  rpi-vstim camera-acceptance --config /path/to/production.toml
  rpi-vstim inspect-session /mnt/experiment-ssd/<session-id> --json
EOF
else
  echo "write-heavy mode selected; operator confirmation is still required before each camera/storage run."
fi
