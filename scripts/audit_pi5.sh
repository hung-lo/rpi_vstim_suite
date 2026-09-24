#!/usr/bin/env bash
set -euo pipefail

target="${1:-pi@10.42.84.10}"
exec ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=5 "$target" 'set -u
python3 --version
cat /etc/os-release
uname -a
uname -m
cat /proc/device-tree/model 2>/dev/null || true
free -h
df -h
which python3
which pip3
which ffmpeg
ls -l /dev/dri/ 2>/dev/null || true
ls -l /dev/video* 2>/dev/null || true
gpioinfo 2>/dev/null || true'
