"""Read-only machine capability report."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .camera.identity import enumerate_rpicam_cameras
from .core.config import Config
from .core.provenance import resolve_source_commit
from .core.storage import _mount_info


def _command(*args: str) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _service(name: str) -> dict[str, bool]:
    installed = bool(_command("systemctl", "list-unit-files", f"{name}.service", "--no-legend"))
    return {"installed": installed, "active": installed and _command("systemctl", "is-active", name) == "active"}


def inspect_machine(config: Config) -> dict[str, object]:
    """Read sysfs, mount metadata and service status; never open hardware devices."""
    model_path = Path("/proc/device-tree/model")
    try:
        model = model_path.read_bytes().decode(errors="replace").rstrip("\x00")
    except OSError:
        model = "unavailable"
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
    except OSError:
        os_name = platform.system()
    connectors = []
    drm_root = Path("/sys/class/drm")
    for status_file in sorted(drm_root.glob("card*-*/status")):
        try:
            status = status_file.read_text(encoding="utf-8").strip()
        except OSError:
            status = "unavailable"
        connectors.append({"name": status_file.parent.name, "status": status})
    camera_status = "unavailable"
    cameras = []
    if shutil.which("rpicam-hello"):
        try:
            cameras = [camera.as_dict() for camera in enumerate_rpicam_cameras()]
            camera_status = "detected"
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            camera_status = "none detected"
    root = config.paths.output_root
    exists = root.is_dir()
    storage = {"output_root": str(root), "exists": exists,
               "writable": exists and os.access(root, os.W_OK | os.X_OK),
               "mount_source": None, "filesystem": None, "free_bytes": None}
    if exists:
        mount = _mount_info(root)
        storage.update(mount_source=mount["source"], filesystem=mount["fstype"],
                       free_bytes=shutil.disk_usage(root).free)
    return {
        "hardware_access": False,
        "model": model,
        "os": os_name,
        "kernel": platform.release(),
        "python": sys.version.split()[0],
        "package_version": __version__,
        "source_commit": resolve_source_commit(),
        "drm_devices": [str(path) for path in sorted(Path("/dev/dri").glob("card*"))],
        "hdmi_connectors": [item for item in connectors if "HDMI" in item["name"]],
        "kms_available": bool(connectors and list(Path("/dev/dri").glob("card*"))),
        "desktop": {"labwc_running": bool(_command("pgrep", "-x", "labwc")),
                    "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
                    "x11": bool(os.environ.get("DISPLAY")),
                    "xwayland_running": bool(_command("pgrep", "-x", "Xwayland"))},
        "cameras": {"status": camera_status, "devices": cameras},
        "gpio_backend_available": importlib.util.find_spec("lgpio") is not None,
        "storage": storage,
        "neurokairos": _service("neurokairos"),
        "chrony": _service("chrony"),
    }
