"""TOML configuration schema and validation."""

from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from rpi_vstim.hardware.lick import MIN_CLASSIFIED_LICK_INTERVAL_MS, RELEASE_STABLE_MS
from rpi_vstim.hardware.policy import (
    LICK_CENTER_GPIO_BCM,
    OPERATOR_BAIT_GPIO_BCM,
    RESERVED_GPIO_BCM,
    SOUND_TRIGGER_1_GPIO_BCM,
    SOUND_TRIGGER_2_GPIO_BCM,
    reserved_gpio_message,
)


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration."""


_LEGACY_REWARD_FIELDS = {
    "reward_num_pulses",
    "reward_pulse_count",
    "reward_pulse_on_sec",
    "reward_pulse_off_sec",
    "pulse_index",
}


def _legacy_reward_fields(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).intersection(_LEGACY_REWARD_FIELDS) | set().union(
            *(_legacy_reward_fields(item) for item in value.values())
        )
    if isinstance(value, (list, tuple)):
        return set().union(*(_legacy_reward_fields(item) for item in value))
    return set()


@dataclass(frozen=True)
class PathsConfig:
    output_root: Path = Path.home() / "rpi_vstim" / "sessions"
    cache_root: Path = Path.home() / "rpi_vstim" / "cache"
    asset_root: Path = Path.home() / "rpi_vstim" / "stimulus_assets"
    reward_state_root: Path = Path.home() / "rpi_vstim" / "reward_state"
    reward_hardware_lock_path: Path = Path("/tmp/rpi-vstim-reward.lock")
    operator_control_socket: Path = Path("/tmp/rpi-vstim-operator.sock")
    operator_event_log: Path = Path("/tmp/rpi-vstim-operator-events.jsonl")


@dataclass(frozen=True)
class DisplayConfig:
    backend: str = "fake"
    ownership: str = ""
    stimulus_connector: str = ""
    preview_connector: str | None = None
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
    reward_right_pin_bcm: int = 20
    reward_center_pin_bcm: int = 21
    reward_4_pin_bcm: int = 7
    airpuff_pin_bcm: int = 8
    suction_pin_bcm: int = 25
    reward_initial_level: int = 0
    suction_initial_level: int = 0
    reward_active_level: int | None = None
    suction_active_level: int | None = None
    reward_open_duration_ms: float | None = None
    reward_target_ul: float | None = None
    reward_calibration_profile: Path | None = None
    lick_pin_bcm: int = 26
    lick_right_pin_bcm: int = 27
    lick_center_pin_bcm: int = LICK_CENTER_GPIO_BCM
    lick_idle_level: int = 0
    lick_active_level: int = 1
    ttl_pin_bcm: int | None = None
    sound_trigger_1_pin_bcm: int = -1
    sound_trigger_2_pin_bcm: int = -1
    release_stable_ms: int = RELEASE_STABLE_MS
    min_classified_lick_interval_ms: int = MIN_CLASSIFIED_LICK_INTERVAL_MS

    def output_line(self, role: str):
        """Resolve only the supported electrical output roles from rig config."""
        from rpi_vstim.hardware.models import OutputLineConfig

        if role in {"reward", "reward_left"} and self.reward_pin_bcm == -1:
            raise ConfigError("reward GPIO is unassigned")
        if role in {"vacuum", "suction"} and self.suction_pin_bcm == -1:
            raise ConfigError("vacuum GPIO is unassigned")
        if role == "reward":
            return OutputLineConfig(
                "reward_left",
                self.chip,
                self.reward_pin_bcm,
                self.reward_initial_level,
                self.reward_active_level,
            )
        if role == "reward_left":
            return self.output_line("reward")
        if role in {"vacuum", "suction"}:
            return OutputLineConfig(
                "vacuum",
                self.chip,
                self.suction_pin_bcm,
                self.suction_initial_level,
                self.suction_active_level,
            )
        raise ConfigError(f"unsupported output role: {role}")


@dataclass(frozen=True)
class OperatorControlsConfig:
    manual_bait_enabled: bool = False
    bait_button_enabled: bool = False
    bait_button_gpio: int = -1
    bait_button_idle_level: int | None = None
    bait_button_active_level: int | None = None
    bait_reward_ul: float | None = None
    minimum_interval_ms: int = 1000
    bait_button_release_stable_ms: int = RELEASE_STABLE_MS
    max_manual_bait_water_ul: float | None = None
    bait_auto_suction: bool = False

    @property
    def manual_bait_min_interval_ms(self) -> int:
        """Backward-compatible descriptive alias for the operator lockout."""
        return self.minimum_interval_ms


@dataclass(frozen=True)
class CameraDeviceConfig:
    id: str
    role: str
    required: bool = False
    backend: str = "auto"
    device: str = ""
    expected_family: str = ""
    requested_width_px: int | None = None
    requested_height_px: int | None = None
    requested_fps: float | None = None
    pixel_format_or_codec: str = ""
    output_extension: str = "h264"
    output_naming_policy: str = "capture"
    startup_timeout_s: float = 5.0
    stop_timeout_s: float = 5.0
    stall_timeout_s: float | None = 30.0

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
    operator_controls: OperatorControlsConfig = field(default_factory=OperatorControlsConfig)
    cameras: CamerasConfig = field(default_factory=CamerasConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)

    def validate(self, *, require_paths: bool = False, repo_root: Path | None = None) -> None:
        """Reject malformed settings and combinations unsafe for experiments."""
        if self.display.backend not in {"fake", "kms", "rpg_legacy"}:
            raise ConfigError(f"unsupported display backend: {self.display.backend}")
        if self.display.ownership not in {"", "direct", "lease"}:
            raise ConfigError(f"unsupported display ownership: {self.display.ownership}")
        if self.display.pixel_format not in {"RGB565", "XRGB8888"}:
            raise ConfigError(f"unsupported pixel format: {self.display.pixel_format}")
        if self.display.backend == "kms" and self.display.ownership not in {"direct", "lease"}:
            raise ConfigError("display ownership is required for the KMS backend")
        if self.display.backend == "kms" and not self.display.stimulus_connector:
            raise ConfigError("display stimulus_connector is required for the KMS backend")
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
        if self.operator_controls.bait_button_gpio not in {-1, OPERATOR_BAIT_GPIO_BCM}:
            raise ConfigError("operator bait button must use canonical BCM GPIO23")
        pins = {
            "reward": self.hardware.reward_pin_bcm,
            "reward_right": self.hardware.reward_right_pin_bcm,
            "reward_center": self.hardware.reward_center_pin_bcm,
            "reward_4": self.hardware.reward_4_pin_bcm,
            "airpuff": self.hardware.airpuff_pin_bcm,
            "suction": self.hardware.suction_pin_bcm,
            "lick": self.hardware.lick_pin_bcm,
            "lick_right": self.hardware.lick_right_pin_bcm,
            "lick_center": self.hardware.lick_center_pin_bcm,
        }
        if self.hardware.ttl_pin_bcm is not None:
            pins["ttl"] = self.hardware.ttl_pin_bcm
        pins["sound_trigger_1"] = self.hardware.sound_trigger_1_pin_bcm
        pins["sound_trigger_2"] = self.hardware.sound_trigger_2_pin_bcm
        pins["operator_bait_button"] = self.operator_controls.bait_button_gpio
        if any(not isinstance(pin, int) or pin < -1 or pin > 27 for pin in pins.values()):
            raise ConfigError("BCM pins must be -1 (unassigned) or between 0 and 27")
        reserved = RESERVED_GPIO_BCM.intersection(pins.values())
        if reserved:
            raise ConfigError(reserved_gpio_message(min(reserved)))
        for pin, roles in (
            (SOUND_TRIGGER_1_GPIO_BCM, {"sound_trigger_1", "operator_bait_button"}),
            (SOUND_TRIGGER_2_GPIO_BCM, {"sound_trigger_2", "ttl"}),
        ):
            if any(name not in roles and assigned == pin for name, assigned in pins.items()):
                raise ConfigError(reserved_gpio_message(pin))
        for name, level in {
            "reward_initial_level": self.hardware.reward_initial_level,
            "suction_initial_level": self.hardware.suction_initial_level,
        }.items():
            if type(level) is not int or level not in (0, 1):
                raise ConfigError(f"{name} must be electrical LOW (0) or HIGH (1)")
        for name, level in {
            "reward_active_level": self.hardware.reward_active_level,
            "suction_active_level": self.hardware.suction_active_level,
        }.items():
            if level is not None and (type(level) is not int or level not in (0, 1)):
                raise ConfigError(f"{name} must be 0, 1, or unset")
        if (self.hardware.lick_idle_level, self.hardware.lick_active_level) != (0, 1):
            raise ConfigError("lick inputs must be configured idle LOW (0) and active HIGH (1)")
        assigned_pins = [pin for pin in pins.values() if pin != -1]
        if len(set(assigned_pins)) != len(assigned_pins):
            raise ConfigError("GPIO pins must be unique")
        if (
            not isinstance(self.hardware.release_stable_ms, int)
            or self.hardware.release_stable_ms <= 0
            or not isinstance(self.hardware.min_classified_lick_interval_ms, int)
            or self.hardware.min_classified_lick_interval_ms <= 0
        ):
            raise ConfigError("lick timing settings must be positive integers")
        if self.hardware.backend not in {"simulated", "lgpio"}:
            raise ConfigError(f"unsupported hardware backend: {self.hardware.backend}")
        if not isinstance(self.hardware.chip, int) or self.hardware.chip < 0:
            raise ConfigError("hardware chip must be a non-negative integer")
        controls = self.operator_controls
        if type(controls.manual_bait_enabled) is not bool:
            raise ConfigError("manual_bait_enabled must be true or false")
        if type(controls.bait_button_enabled) is not bool:
            raise ConfigError("bait_button_enabled must be true or false")
        for name, level in {
            "bait_button_idle_level": controls.bait_button_idle_level,
            "bait_button_active_level": controls.bait_button_active_level,
        }.items():
            if level is not None and (type(level) is not int or level not in (0, 1)):
                raise ConfigError(f"{name} must be 0, 1, or unset")
        if controls.manual_bait_enabled:
            if (
                controls.bait_reward_ul is None
                or type(controls.bait_reward_ul) not in (int, float)
                or not math.isfinite(controls.bait_reward_ul)
                or controls.bait_reward_ul <= 0
            ):
                raise ConfigError("manual bait requires positive bait_reward_ul")
        elif controls.bait_reward_ul is not None and (
            type(controls.bait_reward_ul) not in (int, float)
            or not math.isfinite(controls.bait_reward_ul)
            or controls.bait_reward_ul <= 0
        ):
            raise ConfigError("bait_reward_ul must be positive when configured")
        if controls.bait_button_enabled:
            if controls.bait_button_idle_level is None or controls.bait_button_active_level is None:
                raise ConfigError(
                    "enabled operator bait button requires explicit idle and active levels"
                )
            if controls.bait_button_gpio == -1:
                raise ConfigError("enabled operator bait button requires BCM GPIO23")
            if controls.bait_button_idle_level == controls.bait_button_active_level:
                raise ConfigError("operator bait button idle and active levels must differ")
            if not controls.manual_bait_enabled:
                raise ConfigError("enabled operator bait button requires manual_bait_enabled")
        if (
            not isinstance(controls.minimum_interval_ms, int)
            or controls.minimum_interval_ms <= 0
            or not isinstance(controls.bait_button_release_stable_ms, int)
            or controls.bait_button_release_stable_ms <= 0
        ):
            raise ConfigError("operator bait timing settings must be positive integers")
        if controls.max_manual_bait_water_ul is not None and (
            type(controls.max_manual_bait_water_ul) not in (int, float)
            or not math.isfinite(controls.max_manual_bait_water_ul)
            or controls.max_manual_bait_water_ul <= 0
        ):
            raise ConfigError("max_manual_bait_water_ul must be finite and positive")
        if type(controls.bait_auto_suction) is not bool:
            raise ConfigError("bait_auto_suction must be true or false")
        if self.hardware.reward_open_duration_ms is not None and (
            type(self.hardware.reward_open_duration_ms) not in (int, float)
            or not math.isfinite(self.hardware.reward_open_duration_ms)
            or self.hardware.reward_open_duration_ms <= 0
        ):
            raise ConfigError("reward_open_duration_ms must be finite and positive")
        if self.hardware.reward_target_ul is not None and (
            type(self.hardware.reward_target_ul) not in (int, float)
            or not math.isfinite(self.hardware.reward_target_ul)
            or self.hardware.reward_target_ul <= 0
        ):
            raise ConfigError("reward_target_ul must be positive")
        if (self.hardware.reward_target_ul is None) != (
            self.hardware.reward_calibration_profile is None
        ):
            raise ConfigError(
                "reward_target_ul and reward_calibration_profile must be provided together"
            )
        if self.hardware.reward_open_duration_ms is not None and self.hardware.reward_target_ul is not None:
            raise ConfigError("choose reward_open_duration_ms or calibrated reward_target_ul")
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
            if any(
                value is not None and value <= 0
                for value in (
                    camera.requested_width_px,
                    camera.requested_height_px,
                    camera.requested_fps,
                )
            ):
                raise ConfigError(f"camera requested dimensions/FPS must be positive: {camera.id}")
            if camera.startup_timeout_s <= 0 or camera.stop_timeout_s <= 0:
                raise ConfigError(f"camera timeouts must be positive: {camera.id}")
            if camera.stall_timeout_s is not None and camera.stall_timeout_s <= 0:
                raise ConfigError(f"camera stall_timeout_s must be positive or null: {camera.id}")
            if not camera.output_extension or "/" in camera.output_extension:
                raise ConfigError(f"camera output_extension is invalid: {camera.id}")
            if camera.output_naming_policy != "capture":
                raise ConfigError(f"unsupported camera output_naming_policy: {camera.id}")
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
    if section == "paths" and any(
        isinstance(value, str) and not value.strip() for value in converted.values()
    ):
        raise ConfigError("paths must not be empty")
    for name in known & {
        "output_root",
        "cache_root",
        "asset_root",
        "reward_state_root",
        "reward_hardware_lock_path",
        "operator_control_socket",
        "operator_event_log",
        "reward_calibration_profile",
    }:
        if name in converted:
            converted[name] = None if converted[name] is None else Path(converted[name])
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


def _replace_operator_controls(
    current: OperatorControlsConfig, values: dict[str, Any]
) -> OperatorControlsConfig:
    values = dict(values)
    if "manual_bait_min_interval_ms" in values:
        if "minimum_interval_ms" in values:
            raise ConfigError(
                "configure only one of minimum_interval_ms or manual_bait_min_interval_ms"
            )
        values["minimum_interval_ms"] = values.pop("manual_bait_min_interval_ms")
    return _replace_section(current, values, "operator_controls")


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
    allowed = {
        "paths",
        "display",
        "photodiode",
        "gpio",
        "hardware",
        "operator_controls",
        "cameras",
        "telemetry",
        "session",
        "protocol",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"unknown top-level setting(s): {', '.join(sorted(unknown))}")
    if "gpio" in raw and "hardware" in raw:
        raise ConfigError("use only one of [gpio] or [hardware]")
    found = sorted(_legacy_reward_fields(raw))
    if found:
        raise ConfigError(
            "legacy six-pulse reward setting(s) are not accepted: "
            + ", ".join(found)
            + "; use reward_open_duration_ms or a calibrated reward_target_ul/profile"
        )
    config = Config()
    for name in ("paths", "photodiode", "telemetry", "session"):
        if name in raw:
            config = replace(config, **{name: _replace_section(getattr(config, name), raw[name], name)})
    if "display" in raw:
        config = replace(config, display=_replace_display(config.display, raw["display"]))
    if "operator_controls" in raw:
        config = replace(
            config,
            operator_controls=_replace_operator_controls(
                config.operator_controls, raw["operator_controls"]
            ),
        )
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
    config = config_from_mapping(raw)
    relative_paths = {
        name: (config_path.parent / value).resolve()
        for name in (
            "output_root",
            "cache_root",
            "asset_root",
            "reward_state_root",
            "reward_hardware_lock_path",
            "operator_control_socket",
            "operator_event_log",
        )
        if not (value := getattr(config.paths, name)).is_absolute()
    }
    calibration_profile = config.hardware.reward_calibration_profile
    if calibration_profile is not None and not calibration_profile.is_absolute():
        config = replace(
            config,
            hardware=replace(
                config.hardware,
                reward_calibration_profile=(config_path.parent / calibration_profile).resolve(),
            ),
        )
    if relative_paths:
        config = replace(config, paths=replace(config.paths, **relative_paths))
    return config


def config_json(config: Config) -> str:
    return json.dumps(config.as_dict(), indent=2, sort_keys=True) + "\n"
