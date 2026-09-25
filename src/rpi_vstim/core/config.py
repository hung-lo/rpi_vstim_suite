"""TOML configuration schema and validation."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration."""


@dataclass(frozen=True)
class PathsConfig:
    output_root: Path = Path("/mnt/hd")
    cache_root: Path = Path("/mnt/hd/vstim_cache")
    asset_root: Path = Path("/home/pi/stimulus_assets")
    reward_state_root: Path = Path("/mnt/hd/vstim_reward_assignments")


@dataclass(frozen=True)
class DisplayConfig:
    backend: str = "fake"
    stimulus_connector: str = "HDMI-A-1"
    preview_connector: str | None = "HDMI-A-2"
    width_px: int = 1280
    height_px: int = 720
    refresh_hz: float = 60.0
    require_exact_refresh: bool = True
    refresh_tolerance_hz: float = 0.05
    pixel_format: str = "RGB565"
    calibration_id: str = ""
    physical_width_cm: float = 15.50
    physical_height_cm: float = 8.72
    eye_distance_cm: float = 16.0

    @property
    def connector(self) -> str:
        """Backward-compatible alias for the configured stimulus connector."""
        return self.stimulus_connector


@dataclass(frozen=True)
class PhotodiodeConfig:
    enabled: bool = True
    corner: str = "bottom_right"
    size_px: int = 50
    on_value: int = 255
    off_value: int = 0


@dataclass(frozen=True)
class HardwareConfig:
    backend: str = "simulated"
    chip: int = 0
    reward_pin_bcm: int = 19
    suction_pin_bcm: int = 25
    lick_pin_bcm: int = 26
    ttl_pin_bcm: int | None = None


@dataclass(frozen=True)
class CameraDeviceConfig:
    id: str
    role: str
    required: bool = False
    backend: str = "auto"
    device: str = ""

    @property
    def stable_device_identifier(self) -> str:
        """Stable local identity; never assume /dev/videoN is stable."""
        return self.device


@dataclass(frozen=True)
class CamerasConfig:
    enabled_by_default: bool = False
    record_to_session: bool = True
    verify_output_growth: bool = True
    devices: tuple[CameraDeviceConfig, ...] = ()


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool = False
    required: bool = False
    host: str = ""
    port: int = 5055


@dataclass(frozen=True)
class SessionConfig:
    require_interactive_gate: bool = True
    experimental: bool = False
    simulation: bool = True


@dataclass(frozen=True)
class ProtocolConfig:
    name: str = "natural-images"
    version: str = "placeholder"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    paths: PathsConfig = field(default_factory=PathsConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    photodiode: PhotodiodeConfig = field(default_factory=PhotodiodeConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    cameras: CamerasConfig = field(default_factory=CamerasConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)

    def validate(self, *, require_paths: bool = False, repo_root: Path | None = None) -> None:
        """Reject malformed settings and combinations unsafe for experiments."""
        if self.display.backend not in {"fake", "kms", "rpg_legacy"}:
            raise ConfigError(f"unsupported display backend: {self.display.backend}")
        if self.display.pixel_format not in {"RGB565", "XRGB8888"}:
            raise ConfigError(f"unsupported pixel format: {self.display.pixel_format}")
        if not self.display.stimulus_connector:
            raise ConfigError("display stimulus_connector must not be empty")
        if self.display.width_px <= 0 or self.display.height_px <= 0 or self.display.refresh_hz <= 0:
            raise ConfigError("display dimensions and refresh_hz must be positive")
        if self.display.preview_connector == self.display.stimulus_connector:
            raise ConfigError("display preview_connector must differ from stimulus_connector")
        if self.display.refresh_tolerance_hz < 0:
            raise ConfigError("display refresh_tolerance_hz must not be negative")
        if min(self.display.physical_width_cm, self.display.physical_height_cm, self.display.eye_distance_cm) <= 0:
            raise ConfigError("display geometry must be positive")
        if self.photodiode.size_px <= 0 or not 0 <= self.photodiode.on_value <= 255 or not 0 <= self.photodiode.off_value <= 255:
            raise ConfigError("invalid photodiode settings")
        pins = {
            "reward": self.hardware.reward_pin_bcm,
            "suction": self.hardware.suction_pin_bcm,
            "lick": self.hardware.lick_pin_bcm,
        }
        if self.hardware.ttl_pin_bcm is not None:
            pins["ttl"] = self.hardware.ttl_pin_bcm
        if any(not isinstance(pin, int) or pin < 0 or pin > 27 for pin in pins.values()):
            raise ConfigError("BCM pins must be between 0 and 27")
        if len(set(pins.values())) != len(pins):
            raise ConfigError("GPIO pins must be unique")
        if self.hardware.backend not in {"simulated", "lgpio"}:
            raise ConfigError(f"unsupported hardware backend: {self.hardware.backend}")
        if not isinstance(self.hardware.chip, int) or self.hardware.chip < 0:
            raise ConfigError("hardware chip must be a non-negative integer")
        if not 1 <= self.telemetry.port <= 65535:
            raise ConfigError("telemetry port must be between 1 and 65535")
        if self.telemetry.required and not self.telemetry.enabled:
            raise ConfigError("telemetry.required requires telemetry.enabled")
        if (self.telemetry.enabled or self.telemetry.required) and not self.telemetry.host:
            raise ConfigError("telemetry host is required when telemetry is enabled or required")
        camera_ids = [camera.id for camera in self.cameras.devices]
        camera_roles = [camera.role for camera in self.cameras.devices]
        bound_devices = [camera.device for camera in self.cameras.devices if camera.device]
        if any(not camera.id or not camera.role for camera in self.cameras.devices):
            raise ConfigError("camera id and role must not be empty")
        if len(camera_ids) != len(set(camera_ids)):
            raise ConfigError("camera IDs must be unique")
        if len(camera_roles) != len(set(camera_roles)):
            raise ConfigError("camera roles must be unique")
        if len(bound_devices) != len(set(bound_devices)):
            raise ConfigError("camera devices must be unique")
        supported_camera_backends = {"auto", "v4l2", "libcamera", "rpicam"}
        for camera in self.cameras.devices:
            if camera.backend not in supported_camera_backends:
                raise ConfigError(f"unsupported camera backend: {camera.backend}")
            if self.session.experimental and camera.required and not camera.device:
                raise ConfigError(f"required camera lacks a stable device identity: {camera.id}")
        if self.session.experimental and self.session.simulation:
            raise ConfigError("simulation cannot be combined with experimental mode")
        if self.session.experimental and self.display.backend == "fake":
            raise ConfigError("experimental mode requires a hardware display backend")
        if self.session.experimental and not self.display.calibration_id:
            raise ConfigError("experimental mode requires a display calibration_id")
        if self.session.experimental and self.hardware.backend == "simulated":
            raise ConfigError("experimental mode requires a hardware GPIO backend")
        if require_paths:
            writable_paths = {
                "output_root": self.paths.output_root,
                "cache_root": self.paths.cache_root,
                "reward_state_root": self.paths.reward_state_root,
            }
            for name, path in writable_paths.items():
                _validate_directory(path, name, os.W_OK, "writable")
            _validate_directory(self.paths.asset_root, "asset_root", os.R_OK, "readable")
            if repo_root is not None:
                root = repo_root.resolve()
                try:
                    self.paths.reward_state_root.resolve().relative_to(root)
                except ValueError:
                    pass
                else:
                    raise ConfigError("reward_state_root must not be inside the code checkout")

    def as_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _validate_directory(path: Path, name: str, access: int, access_label: str) -> None:
    path = Path(path)
    if not path.is_dir() or not os.access(path, access):
        raise ConfigError(f"{name} must be an existing {access_label} directory: {path}")


def _replace_section(current: Any, values: dict[str, Any], section: str) -> Any:
    known = {item.name for item in fields(current)}
    unknown = set(values) - known
    if unknown:
        raise ConfigError(f"unknown {section} setting(s): {', '.join(sorted(unknown))}")
    converted = dict(values)
    for name in known & {"output_root", "cache_root", "asset_root", "reward_state_root"}:
        if name in converted:
            converted[name] = Path(converted[name])
    return replace(current, **converted)


def _replace_display(current: DisplayConfig, values: dict[str, Any]) -> DisplayConfig:
    values = dict(values)
    if "connector" in values:
        if "stimulus_connector" in values:
            raise ConfigError("display must use only one of connector or stimulus_connector")
        values["stimulus_connector"] = values.pop("connector")
    if values.get("preview_connector") == "":
        values["preview_connector"] = None
    return _replace_section(current, values, "display")


def _replace_cameras(current: CamerasConfig, values: dict[str, Any]) -> CamerasConfig:
    known = {item.name for item in fields(current)}
    unknown = set(values) - known
    if unknown:
        raise ConfigError(f"unknown cameras setting(s): {', '.join(sorted(unknown))}")
    raw_devices = values.get("devices", current.devices)
    devices: list[CameraDeviceConfig] = []
    for raw_device in raw_devices:
        device_values = dict(raw_device)
        if "stable_device_identifier" in device_values:
            if "device" in device_values:
                raise ConfigError("camera device must use only one of device or stable_device_identifier")
            device_values["device"] = device_values.pop("stable_device_identifier")
        allowed = {item.name for item in fields(CameraDeviceConfig)}
        unknown_device = set(device_values) - allowed
        if unknown_device:
            raise ConfigError(
                f"unknown camera device setting(s): {', '.join(sorted(unknown_device))}"
            )
        devices.append(CameraDeviceConfig(**device_values))
    return replace(current, **{**values, "devices": tuple(devices)})


def config_from_mapping(raw: dict[str, Any]) -> Config:
    allowed = {"paths", "display", "photodiode", "gpio", "hardware", "cameras", "telemetry", "session", "protocol"}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"unknown top-level setting(s): {', '.join(sorted(unknown))}")
    if "gpio" in raw and "hardware" in raw:
        raise ConfigError("use only one of [gpio] or [hardware]")
    config = Config()
    for name in ("paths", "photodiode", "telemetry", "session"):
        if name in raw:
            config = replace(config, **{name: _replace_section(getattr(config, name), raw[name], name)})
    if "display" in raw:
        config = replace(config, display=_replace_display(config.display, raw["display"]))
    if "cameras" in raw:
        config = replace(config, cameras=_replace_cameras(config.cameras, raw["cameras"]))
    hardware_section = raw.get("hardware", raw.get("gpio"))
    if hardware_section is not None:
        config = replace(config, hardware=_replace_section(config.hardware, hardware_section, "hardware"))
    if "protocol" in raw:
        values = dict(raw["protocol"])
        name = values.pop("name", config.protocol.name)
        version = values.pop("version", config.protocol.version)
        parameters = dict(values.pop("parameters", config.protocol.parameters))
        parameters.update(values)
        config = replace(config, protocol=ProtocolConfig(name=name, version=version, parameters=parameters))
    config.validate()
    return config


def load_config(path: Path | str | None = None) -> Config:
    if path is None:
        return Config()
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    return config_from_mapping(raw)


def config_json(config: Config) -> str:
    return json.dumps(config.as_dict(), indent=2, sort_keys=True) + "\n"
