#!/usr/bin/env bash
set -euo pipefail

target="${1:-pi@10.42.84.10}"
exec ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=5 "$target" 'set -u

section() {
    printf "\n== %s ==\n" "$1"
}

optional() {
    if command -v "$1" >/dev/null 2>&1; then
        "$@" || true
    else
        printf "%s: unavailable\n" "$1"
    fi
}

section identity
hostname || true
id || true
groups || true

section model
cat /proc/device-tree/model 2>/dev/null || true
cat /etc/os-release 2>/dev/null || true

section python
command -v python3 || true
python3 --version 2>&1 || true
python3 -c "import sys; print(sys.executable); print(sys.version)" 2>/dev/null || true

section kernel
uname -a || true
uname -m || true

section resources
free -h || true
df -h || true
findmnt 2>/dev/null || true

section tools
for tool in pip3 ffmpeg; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf "%s: " "$tool"
        command -v "$tool"
    else
        printf "%s: unavailable\n" "$tool"
    fi
done

section drm
ls -la /dev/dri 2>/dev/null || true
for status in /sys/class/drm/*/status; do
    [ -f "$status" ] || continue
    connector="${status%/status}"
    printf "%s: " "${connector##*/}"
    cat "$status"
    modes="$connector/modes"
    if [ -f "$modes" ]; then
        printf "%s modes:\n" "${connector##*/}"
        cat "$modes"
    fi
done

section framebuffer
ls -la /dev/fb* 2>/dev/null || true

section gpio
ls -la /dev/gpiochip* 2>/dev/null || true
optional gpioinfo

section cameras
ls -la /dev/video* 2>/dev/null || true
ls -la /dev/v4l/by-id 2>/dev/null || true
ls -la /dev/v4l/by-path 2>/dev/null || true
ls -la /dev/media* 2>/dev/null || true
for device in /dev/video*; do
    [ -e "$device" ] || continue
    optional v4l2-ctl --all --device "$device"
done
optional v4l2-ctl --list-devices
optional rpicam-hello --list-cameras
optional libcamera-hello --list-cameras
optional lsusb
optional lsusb -t
for media in /sys/class/media/*; do
    [ -e "$media" ] || continue
    printf "%s:\n" "$media"
    cat "$media/name" 2>/dev/null || true
done

section time
optional timedatectl status

section network
optional ip -brief address

section drm_modules
if [ -r /proc/modules ]; then
    awk '\''$1 == "vc4" || $1 ~ /^drm/ { print }'\'' /proc/modules
fi
for module in vc4 drm; do
    if [ -d "/sys/module/$module" ]; then
        printf "%s: loaded\n" "$module"
    else
        printf "%s: not loaded or unavailable\n" "$module"
    fi
done

section display_environment
printf "XDG_SESSION_TYPE=%s\n" "${XDG_SESSION_TYPE-}"
printf "WAYLAND_DISPLAY=%s\n" "${WAYLAND_DISPLAY-}"
printf "DISPLAY=%s\n" "${DISPLAY-}"
'
