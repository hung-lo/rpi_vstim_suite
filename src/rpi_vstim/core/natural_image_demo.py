"""Composition runner for the first real natural-image/lick/camera demo."""

from __future__ import annotations

import json
import math
import shutil
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

from rpi_vstim.audio import AudioClip, AudioOutput, load_pilot_clips
from rpi_vstim.camera import (
    CameraCaptureSpec,
    CameraIdentity,
    CameraPreviewEnvironment,
    LocalCameraSupervisor,
    build_rpicam_command,
    enumerate_rpicam_cameras,
    resolve_camera_identities,
    resolve_camera_preview_environment,
)
from rpi_vstim.control import ExperimentControl
from rpi_vstim.core.assets import AssetPreparer, AssetResolver, build_selected_asset_manifest
from rpi_vstim.core.camera import CameraState
from rpi_vstim.core.config import Config, ConfigError
from rpi_vstim.core.preflight import PreflightReport
from rpi_vstim.core.session import atomic_write_json, new_session
from rpi_vstim.core.storage import prepare_session_output_root
from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.display.kms import KmsDisplayBackend
from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.transport import DisplaySequenceFrame, DisplaySequenceMetadata
from rpi_vstim.hardware.lgpio_lick import ClassifiedLick, LgpioLickMonitor, RawLickEdge
from rpi_vstim.protocols.audio_pilot import ASSET_ROOT as PILOT_AUDIO_ASSET_ROOT
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan, discover_images
from rpi_vstim.telemetry.lick_state import LickTelemetryState

DEMO_CAMERA_WIDTH = 640
DEMO_CAMERA_HEIGHT = 480
DEMO_CAMERA_FPS = 30.0
DEMO_CAMERA_CODEC = "h264"
DEMO_CAMERA_EXTENSION = "mp4"
DEMO_PREVIEW_GEOMETRIES = ((0, 0, 512, 384), (512, 0, 512, 384))
DEFAULT_DEMO_IMAGE_COUNT = 20
AUDIO_COEXISTENCE_ORDER = ("beep", "buzz", "white_noise")


@dataclass(frozen=True)
class AudioCoexistenceSettings:
    device_name_match: str
    gains_db: dict[str, float] = field(default_factory=lambda: {
        stimulus_id: 0.0 for stimulus_id in AUDIO_COEXISTENCE_ORDER
    })
    sequence: tuple[str, ...] = AUDIO_COEXISTENCE_ORDER
    start_delay_s: float = 10.0
    interval_s: float = 15.0

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        device_name_match: str,
        gains_db: dict[str, float],
    ) -> AudioCoexistenceSettings:
        values = config.protocol.parameters.get("audio_coexistence", {})
        if not isinstance(values, dict):
            raise TypeError("protocol.parameters.audio_coexistence must be a table")
        unknown = set(values) - {"sequence", "start_delay_s", "interval_s"}
        if unknown:
            raise ValueError(
                "unknown audio coexistence setting(s): " + ", ".join(sorted(unknown))
            )
        sequence = values.get("sequence", AUDIO_COEXISTENCE_ORDER)
        if not isinstance(sequence, (list, tuple)):
            raise TypeError("audio coexistence sequence must be an array of stimulus IDs")
        return cls(
            device_name_match=device_name_match,
            gains_db=gains_db,
            sequence=tuple(sequence),
            start_delay_s=values.get("start_delay_s", 10.0),
            interval_s=values.get("interval_s", 15.0),
        )

    def __post_init__(self) -> None:
        if not isinstance(self.device_name_match, str) or not self.device_name_match.strip():
            raise ValueError("audio coexistence requires a configured device name match")
        if not isinstance(self.gains_db, dict) or set(self.gains_db) != set(AUDIO_COEXISTENCE_ORDER):
            raise ValueError("audio gains must specify beep, buzz, and white_noise")
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in self.gains_db.values()):
            raise ValueError("audio gains must be finite")
        if not isinstance(self.sequence, (tuple, list)) or not self.sequence or any(
            stimulus_id not in AUDIO_COEXISTENCE_ORDER for stimulus_id in self.sequence
        ):
            raise ValueError("audio coexistence sequence must contain known pilot stimulus IDs")
        object.__setattr__(self, "sequence", tuple(self.sequence))
        if (type(self.start_delay_s) not in (int, float)
                or not math.isfinite(self.start_delay_s) or self.start_delay_s < 0
                or type(self.interval_s) not in (int, float)
                or not math.isfinite(self.interval_s) or self.interval_s < 3.0):
            raise ValueError("audio schedule needs a non-negative delay and interval of at least 3 s")


@dataclass(frozen=True)
class ScheduledAudio:
    audio_index: int
    stimulus_id: str
    filename: str
    planned_offset_s: float


def build_audio_coexistence_plan(
    duration_s: float,
    clips: dict[str, AudioClip],
    settings: AudioCoexistenceSettings,
) -> tuple[ScheduledAudio, ...]:
    if not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError("audio schedule duration must be finite and non-negative")
    scheduled = []
    offset = settings.start_delay_s
    while offset + 3.0 <= duration_s:
        stimulus_id = settings.sequence[len(scheduled) % len(settings.sequence)]
        scheduled.append(ScheduledAudio(
            len(scheduled) + 1, stimulus_id, clips[stimulus_id].filename, offset
        ))
        offset += settings.interval_s
    return tuple(scheduled)


def _latency_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median_ms": statistics.median(ordered),
        "mean_ms": statistics.mean(ordered),
        "sd_ms": statistics.pstdev(ordered),
        "min_ms": ordered[0],
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "max_ms": ordered[-1],
    }


def _audio_summary(
    diagnostics: dict[str, Any],
    schedule: tuple[ScheduledAudio, ...],
    request_indices: list[int],
    latencies_ms: list[float],
    errors: list[str],
    settings: AudioCoexistenceSettings,
) -> dict[str, Any]:
    return {
        **diagnostics,
        "planned_sounds": len(schedule),
        "duplicate_requests": len(request_indices) - len(set(request_indices)),
        "duplicate_callback_starts": max(
            0, diagnostics.get("callback_starts", 0) - diagnostics.get("requested_sounds", 0)
        ),
        "request_to_callback_latency": _latency_summary(latencies_ms),
        "request_to_callback_latency_ms": latencies_ms,
        "device_name_match": settings.device_name_match,
        "gain_db": settings.gains_db,
        "errors": errors,
    }


def _play_coexistence_audio(
    audio: AudioOutput,
    schedule: tuple[ScheduledAudio, ...],
    events: UnifiedEventStream,
    clock: SessionClock,
    start_ns: int,
    stop: Event,
    latencies_ms: list[float],
    request_indices: list[int],
    errors: list[str],
) -> None:
    for trial in schedule:
        planned_ns = start_ns + round(trial.planned_offset_s * 1_000_000_000)
        if stop.wait(max(0.0, (planned_ns - time.monotonic_ns()) / 1_000_000_000)):
            return
        request_ns = time.monotonic_ns()
        request_indices.append(trial.audio_index)
        fields = {
            "audio_index": trial.audio_index,
            "stimulus_id": trial.stimulus_id,
            "filename": trial.filename,
            "planned_offset_s": trial.planned_offset_s,
            "planned_request_monotonic_ns": planned_ns,
            "planned_request_utc_ns": clock.fields(planned_ns)["utc_ns"],
        }
        events.emit_reliable("AUDIO_TRIAL_START", source_monotonic_ns=request_ns, **fields)
        events.emit_reliable("AUDIO_REQUEST", source_monotonic_ns=request_ns, **fields)
        try:
            result = audio.play(trial.stimulus_id)
        except Exception as exc:  # noqa: BLE001 - report the failure and stop later requests.
            errors.append(f"audio request {trial.audio_index}: {exc}")
            events.emit_reliable(
                "AUDIO_TRIAL_END", audio_index=trial.audio_index,
                stimulus_id=trial.stimulus_id, error=str(exc),
            )
            return
        if result.callback_monotonic_ns:
            latency_ms = (result.callback_monotonic_ns - request_ns) / 1_000_000
            latencies_ms.append(latency_ms)
            events.emit_reliable(
                "AUDIO_CALLBACK_START",
                source_monotonic_ns=result.callback_monotonic_ns,
                **fields,
                callback_utc_ns=result.callback_utc_ns,
                request_to_callback_ms=latency_ms,
                callback_semantics="PCM callback start; not physical acoustic onset",
            )
        failure = result.error or (
            f"audio callback failed for request {trial.audio_index}"
            if not result.callback_monotonic_ns else ""
        )
        if result.status_errors:
            failure = failure or f"audio callback status errors: {result.status_errors}"
        events.emit_reliable(
            "AUDIO_TRIAL_END",
            audio_index=trial.audio_index,
            stimulus_id=trial.stimulus_id,
            callback_status_errors=result.status_errors,
            error=failure,
        )
        if failure:
            errors.append(failure)
            return


class NaturalImageDemoError(RuntimeError):
    """Raised when the integrated demo cannot be started safely."""


@dataclass
class NaturalImageDemoResult:
    session_root: Path
    status: str
    error: str | None
    raw_lick_count: dict[str, int]
    classified_lick_count: dict[str, int]
    camera_manifest: list[dict[str, Any]]
    event_diagnostics: dict[str, Any]
    display_payload: dict[str, Any] | None = None
    camera_preview: dict[str, object] = field(default_factory=dict)
    audio_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETE"


@dataclass(frozen=True)
class PreparedNaturalImageDemo:
    plan: Any
    asset_manifest: Any


def prepare_natural_image_demo(
    config: Config,
    *,
    seed: int = 0,
    image_count: int | None = None,
    use_licks: bool = False,
    use_cameras: bool = False,
    camera_preview: bool = False,
    session_id: str = "preflight",
    simulate: bool = False,
    enumerate_cameras: Callable[[], tuple[Any, ...]] = enumerate_rpicam_cameras,
) -> PreparedNaturalImageDemo:
    """Validate a natural-image run without creating a session or starting hardware."""
    if not session_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in session_id
    ):
        raise ValueError("session_id contains unsupported characters")
    if simulate:
        if use_licks or use_cameras or camera_preview:
            raise ConfigError("simulated natural-image runs cannot request physical GPIO or cameras")
        config = _simulation_config(config)
        config.validate()
    else:
        validate_demo_config(
            config, use_licks=use_licks, use_cameras=use_cameras, preview=camera_preview
        )
    prepare_session_output_root(config.paths.output_root)
    session_root = config.paths.output_root / session_id
    if session_root.exists() or session_root.is_symlink():
        raise FileExistsError(f"session already exists: {session_id}")
    plan = build_demo_plan(config, seed=seed, image_count=image_count)
    resolver = AssetResolver(config.paths.asset_root)
    manifest = build_selected_asset_manifest(
        plan,
        resolver,
        target_width_px=config.display.width_px,
        target_height_px=config.display.height_px,
        transform=str(plan.metadata.get("asset_transform", "crop")),
        background_value=int(plan.metadata.get("background_gray", 127)),
    )
    if use_cameras:
        preview_environment = resolve_camera_preview_environment() if camera_preview else None
        _resolve_camera_specs(
            config,
            config.paths.output_root / session_id,
            preview=camera_preview,
            preview_environment=preview_environment,
            enumerate_cameras=enumerate_cameras,
        )
    return PreparedNaturalImageDemo(plan, manifest)


def _simulation_config(config: Config) -> Config:
    """Keep rig geometry while ensuring the session and display are simulated."""
    return replace(
        config,
        display=replace(
            config.display,
            backend="fake",
            ownership="",
            stimulus_connector="SIMULATED",
            preview_connector=None,
        ),
        hardware=replace(config.hardware, backend="simulated"),
        session=replace(config.session, experimental=False, simulation=True),
    )


def validate_demo_config(config: Config, *, use_licks: bool, use_cameras: bool, preview: bool) -> None:
    config.validate()
    if config.display.backend != "kms" or config.display.ownership != "lease":
        raise ConfigError("natural-image demo requires the leased KMS display backend")
    if config.display.stimulus_connector != "HDMI-A-2":
        raise ConfigError("natural-image demo requires stimulus connector HDMI-A-2")
    if preview and config.display.preview_connector != "HDMI-A-1":
        raise ConfigError("camera preview requires preview connector HDMI-A-1")
    if use_licks:
        if config.hardware.backend != "lgpio":
            raise ConfigError("real lick demo requires the lgpio hardware backend")
        if (config.hardware.lick_pin_bcm, config.hardware.lick_right_pin_bcm) != (26, 27):
            raise ConfigError("natural-image demo only permits BCM26/27 lick inputs")
        if (config.hardware.lick_idle_level, config.hardware.lick_active_level) != (0, 1):
            raise ConfigError("natural-image demo requires idle LOW / active HIGH licks")
    if use_cameras and len(config.cameras.devices) != 2:
        raise ConfigError("natural-image demo requires exactly two configured CSI cameras")
    if preview and not use_cameras:
        raise ConfigError("--camera-preview requires --cameras")


def build_demo_plan(
    config: Config,
    *,
    seed: int,
    image_count: int | None,
    camera_ids: tuple[str, ...] = (),
):
    resolver = AssetResolver(config.paths.asset_root)
    images = discover_images(config.paths.asset_root)
    if not images:
        raise NaturalImageDemoError(f"natural-image asset root contains no images: {resolver.root}")
    parameters = config.protocol.parameters
    selected_count = image_count
    if selected_count is None:
        selected_count = int(parameters.get("image_count", DEFAULT_DEMO_IMAGE_COUNT))
    if selected_count <= 0:
        raise ValueError("demo image_count must be positive")
    return build_plan(
        NaturalImageSettings(
            images=images,
            seed=seed,
            trial_count=parameters.get("trial_count"),
            image_count=selected_count,
            repeat_count=int(parameters.get("repeat_count", 1)),
            selection_seed=int(parameters.get("selection_seed", 777)),
            refresh_hz=config.display.refresh_hz,
            image_duration_s=float(parameters.get("image_duration_s", 0.5)),
            iti_frames=tuple(parameters.get("iti_frames", (42, 60))),
            initial_gray_frames=int(parameters.get("initial_gray_frames", 180)),
            final_gray_frames=int(parameters.get("final_gray_frames", 180)),
            compatibility_profile=str(
                parameters.get("compatibility_profile", "natural_legacy_plain")
            ),
            camera_ids=camera_ids,
        )
    )


def _resolve_camera_specs(
    config: Config,
    session_root: Path,
    *,
    preview: bool,
    preview_environment: CameraPreviewEnvironment | None = None,
    enumerate_cameras: Callable[[], tuple[Any, ...]] = enumerate_rpicam_cameras,
) -> tuple[tuple[CameraCaptureSpec, ...], tuple[str, ...]]:
    available = enumerate_cameras()
    configured = tuple(
        CameraIdentity(device.id, device.device, device.expected_family)
        for device in config.cameras.devices
    )
    report = resolve_camera_identities(configured, available)
    if not report.passed:
        raise NaturalImageDemoError(f"camera identity resolution failed: {report.as_dict()}")
    by_id = {camera.camera_id: camera for camera in report.resolved}
    specs: list[CameraCaptureSpec] = []
    commands: list[str] = []
    for index, device in enumerate(config.cameras.devices):
        resolved = by_id[device.id]
        preview_enabled = bool(preview_environment and preview_environment.enabled)
        geometry = DEMO_PREVIEW_GEOMETRIES[index] if preview_enabled else None
        output_path = session_root / "camera" / device.id / f"capture.{DEMO_CAMERA_EXTENSION}"
        base = CameraCaptureSpec(
            camera_id=device.id,
            role=device.role,
            stable_device_identifier=device.stable_device_identifier,
            required=True,
            backend=device.backend,
            command=(),
            output_extension=DEMO_CAMERA_EXTENSION,
            requested_width_px=DEMO_CAMERA_WIDTH,
            requested_height_px=DEMO_CAMERA_HEIGHT,
            requested_fps=DEMO_CAMERA_FPS,
            pixel_format_or_codec=DEMO_CAMERA_CODEC,
            startup_timeout_s=device.startup_timeout_s,
            stop_timeout_s=device.stop_timeout_s,
            stall_timeout_s=device.stall_timeout_s,
            resolved_camera=resolved,
            preview_enabled=preview_enabled,
            preview_requested=preview,
            preview_geometry=geometry,
            preview_connector=config.display.preview_connector if preview_enabled else None,
            child_environment=preview_environment.environment if preview_enabled else None,
        )
        command = build_rpicam_command(base, output_path, resolved_camera=resolved)
        specs.append(base.__class__(**{**base.__dict__, "command": command}))
        commands.append(" ".join(command))
    return tuple(specs), tuple(commands)


def _camera_event_fields(status: Any) -> dict[str, Any]:
    return {
        "camera_id": status.camera_id,
        "camera_role": status.role,
        "stable_device_identifier": status.stable_device_identifier,
        "requested_selector": status.runtime_selector,
        "backend": status.backend,
        "width": status.requested_width_px,
        "height": status.requested_height_px,
        "fps": status.requested_fps,
        "codec": status.pixel_format_or_codec,
        "recording_path": status.output_path,
        "preview_enabled": status.preview_enabled,
        "preview_requested": status.preview_requested,
        "preview_geometry": status.preview_geometry,
        "preview_connector": status.preview_connector,
    }


def _trace_timestamp(
    payload: dict[str, Any],
    frame_index: int,
    *,
    traces: dict[int, dict[str, Any]] | None = None,
    fallback_start_ns: int | None,
    refresh_hz: float,
) -> tuple[int | None, dict[str, Any]]:
    if traces is None:
        traces = {
            int(item["frame_index"]): item
            for item in payload.get("flip_events", [])
            if isinstance(item, dict) and "frame_index" in item
        }
    item = traces.get(frame_index)
    if (
        item is not None
        and payload.get("kernel_timestamp_clock") == "monotonic"
        and int(item.get("kernel_event_ns", 0)) > 0
    ):
        return int(item["kernel_event_ns"]), {
            "timing_source": "drm_kernel_vblank_monotonic",
            "kernel_sequence": item.get("kernel_sequence"),
            "kernel_event_ns": item.get("kernel_event_ns"),
            "callback_monotonic_ns": item.get("callback_monotonic_ns"),
            "callback_realtime_ns": item.get("callback_realtime_ns"),
        }
    if item is not None and int(item.get("callback_monotonic_ns", 0)) > 0:
        return int(item["callback_monotonic_ns"]), {
            "timing_source": "drm_callback_monotonic",
            "kernel_sequence": item.get("kernel_sequence"),
            "kernel_event_ns": item.get("kernel_event_ns"),
            "callback_realtime_ns": item.get("callback_realtime_ns"),
        }
    if fallback_start_ns is not None:
        return fallback_start_ns + int(frame_index * 1_000_000_000 / refresh_hz), {
            "timing_source": "planned_from_display_callback",
        }
    return None, {"timing_source": "dispatch_only"}


def _scientific_display_interval(
    payload: dict[str, Any] | None,
) -> tuple[tuple[int, int] | None, str | None]:
    if payload is None:
        return None, None
    if payload.get("kernel_timestamp_clock") == "monotonic":
        start = payload.get("first_page_flip_kernel_event_ns")
        end = payload.get("last_page_flip_kernel_event_ns")
        if start and end:
            return (int(start), int(end)), "kernel_event_monotonic"
    start = payload.get("first_page_flip_callback_monotonic_ns")
    end = payload.get("last_page_flip_callback_monotonic_ns")
    if start and end:
        return (int(start), int(end)), "callback_monotonic"
    return None, None


def _emit_display_boundary_events(
    stream: UnifiedEventStream,
    plan: Any,
    payload: dict[str, Any],
    *,
    manifest: Any,
    refresh_hz: float,
) -> None:
    by_name = {entry.relative_path: entry for entry in manifest.entries}
    if payload.get("simulated"):
        completed_frames = int(payload.get("completed_frame_count", 0))
        for event in plan.events:
            if not event.frame_count or event.planned_start_frame >= completed_frames:
                continue
            fields = {
                "planned_start_frame": event.planned_start_frame,
                "planned_frame_count": event.frame_count,
                "planned_relative_start_s": event.planned_start_frame / refresh_hz,
                "timing_source": "simulation_plan_only",
                "physical_kms_trace": False,
                "event_id": event.event_id,
                "sequence_id": event.sequence_id or event.event_id,
                "trial_id": event.trial_id,
                "photodiode_state": event.photodiode,
            }
            if event.kind == "image":
                filename = str(event.metadata["image"])
                entry = by_name[filename]
                fields.update(filename=filename, image_sha256=entry.sha256)
            stream.emit_reliable(
                "SIMULATED_STIMULUS_PLAN_EVENT", kind=event.kind, **fields
            )
        stream.emit_reliable(
            "SIMULATED_DISPLAY_COMPLETE",
            completed_frame_count=completed_frames,
            timing_source="simulation_count_only",
            physical_kms_trace=False,
        )
        return
    traces = {
        int(item["frame_index"]): item
        for item in payload.get("flip_events", [])
        if isinstance(item, dict) and "frame_index" in item
    }
    first_callback = payload.get("first_page_flip_callback_monotonic_ns")
    total_frames = int(payload.get("completed_frame_count", plan.total_frames))
    for event in plan.events:
        if not event.frame_count or event.planned_start_frame >= total_frames:
            continue
        source, timing = _trace_timestamp(
            payload,
            event.planned_start_frame,
            traces=traces,
            fallback_start_ns=int(first_callback) if first_callback else None,
            refresh_hz=refresh_hz,
        )
        fields = {
            "event_id": event.event_id,
            "sequence_id": event.sequence_id or event.event_id,
            "trial_id": event.trial_id,
            "logical_frame_index": event.planned_start_frame,
            "frame_count": event.frame_count,
            "photodiode_state": event.photodiode,
            **timing,
        }
        if event.kind == "image":
            filename = str(event.metadata["image"])
            entry = by_name[filename]
            stream.emit_reliable(
                "IMAGE_ONSET",
                source_monotonic_ns=source,
                image_index=int(event.trial_id or 0),
                filename=filename,
                image_sha256=entry.sha256,
                **fields,
            )
            if event.planned_start_frame + event.frame_count <= total_frames:
                end_source, end_timing = _trace_timestamp(
                    payload,
                    event.planned_start_frame + event.frame_count,
                    traces=traces,
                    fallback_start_ns=int(first_callback) if first_callback else None,
                    refresh_hz=refresh_hz,
                )
                stream.emit_reliable(
                    "IMAGE_OFFSET",
                    source_monotonic_ns=end_source,
                    image_index=int(event.trial_id or 0),
                    filename=filename,
                    image_sha256=entry.sha256,
                    logical_frame_index=event.planned_start_frame + event.frame_count,
                    timing_source=end_timing["timing_source"],
                )
            else:
                stream.emit_reliable(
                    "STIMULUS_TRUNCATED",
                    logical_frame_index=event.planned_start_frame,
                    completed_frame_count=total_frames,
                    trial_id=event.trial_id,
                    filename=filename,
                )
        else:
            stream.emit_reliable("GRAY_ONSET", source_monotonic_ns=source, **fields)
    if total_frames:
        stream.emit_reliable(
            "DISPLAY_TRACE_COMPLETE",
            source_monotonic_ns=payload.get("last_page_flip_callback_monotonic_ns") or None,
            completed_frame_count=total_frames,
            kernel_sequence_contiguous=payload.get("kernel_sequence_contiguous"),
            missed_vblank_count=payload.get("missed_vblank_count"),
            estimated_dropped_frame_count=payload.get("estimated_dropped_frame_count"),
        )


def _write_demo_metadata(
    session_root: Path,
    *,
    mouse_id: str,
    event_diagnostics: dict[str, Any],
    status: str,
    error: str | None,
    raw_counts: dict[str, int],
    classified_counts: dict[str, int],
    camera_manifest: list[dict[str, Any]],
    camera_commands: tuple[str, ...],
    lick_monitor_diagnostics: dict[str, Any] | None,
    camera_preview: dict[str, object],
    audio_summary: dict[str, Any],
    operator_control: dict[str, Any] | None = None,
    simulated: bool = False,
) -> None:
    for name in ("provenance.json", "final_status.json"):
        path = session_root / name
        if not path.is_file():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        value["natural_image_demo"] = {
            "mouse_id": mouse_id,
            "reward": "DISABLED",
            "vacuum": "DISABLED",
            "gpio_used": [] if simulated else [26, 27],
            "gpio_untouched": [7, 8, 9, 15, 19, 20, 21, 23, 24, 25],
            "raw_lick_count": raw_counts,
            "classified_lick_count": classified_counts,
            "lick_monitor": lick_monitor_diagnostics,
            "camera_manifest": camera_manifest,
            "camera_commands": list(camera_commands),
            "camera_preview": camera_preview,
            "event_log": event_diagnostics,
        }
        if simulated:
            value["natural_image_demo"].update(
                simulated=True,
                display_backend="simulated",
                physical_kms_trace=False,
            )
        if audio_summary:
            value["audio_coexistence"] = audio_summary
        if operator_control is not None:
            value["operator_control"] = operator_control
        if name == "final_status.json":
            value["status"] = status
            if error:
                value["error"] = error
        atomic_write_json(path, value)
    manifest_path = session_root / "session_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["unified_event_log"] = event_diagnostics
        manifest["natural_image_demo_status"] = status
        if simulated:
            manifest.update(simulated=True, display_backend="simulated", physical_kms_trace=False)
        if audio_summary:
            manifest["audio_coexistence"] = audio_summary
        if operator_control is not None:
            manifest["operator_control"] = operator_control
        atomic_write_json(manifest_path, manifest)


def write_operator_control_metadata(session_root: Path, metadata: dict[str, Any]) -> None:
    """Refresh the final control provenance after the control worker reaches terminal state."""
    atomic_write_json(session_root / "operator_control.json", metadata)
    for name in ("provenance.json", "session_manifest.json", "final_status.json"):
        path = session_root / name
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            value["operator_control"] = metadata
            atomic_write_json(path, value)


def run_natural_image_demo(
    config: Config,
    *,
    mouse_id: str,
    session_id: str,
    seed: int = 0,
    image_count: int | None = None,
    use_licks: bool = False,
    use_cameras: bool = False,
    camera_preview: bool = False,
    native_binary: Path | str | None = None,
    audio: AudioOutput | None = None,
    audio_settings: AudioCoexistenceSettings | None = None,
    prepared: PreparedNaturalImageDemo | None = None,
    control: ExperimentControl | None = None,
    simulate: bool = False,
    enumerate_cameras: Callable[[], tuple[Any, ...]] = enumerate_rpicam_cameras,
) -> NaturalImageDemoResult:
    if simulate:
        if (
            use_licks
            or use_cameras
            or camera_preview
            or audio is not None
            or audio_settings is not None
        ):
            raise ConfigError(
                "simulated natural-image runs cannot request physical GPIO, cameras, or audio"
            )
        config = _simulation_config(config)
    if prepared is None:
        if simulate:
            config.validate()
        else:
            validate_demo_config(
                config, use_licks=use_licks, use_cameras=use_cameras, preview=camera_preview
            )
        plan = build_demo_plan(config, seed=seed, image_count=image_count)
        manifest = None
    else:
        plan = prepared.plan
        manifest = prepared.asset_manifest
    if (audio is None) != (audio_settings is None):
        raise ValueError("audio output and audio settings must be supplied together")
    audio_clips = load_pilot_clips(PILOT_AUDIO_ASSET_ROOT) if audio is not None else {}
    audio_schedule = (
        build_audio_coexistence_plan(
            plan.total_frames / config.display.refresh_hz, audio_clips, audio_settings
        )
        if audio_settings is not None else ()
    )
    if audio_settings is not None and not audio_schedule:
        raise ValueError("natural-image plan is too short for the configured audio schedule")
    session = new_session(config, protocol_name="natural-images", session_id=session_id, seed=seed)
    session.write_initial_outputs()
    control_metadata = control.provenance() if control is not None else None
    start_metadata = (control_metadata or {}).get("start")
    clock = (
        SessionClock(
            session_id,
            int(start_metadata["accepted_utc_ns"]),
            int(start_metadata["accepted_monotonic_ns"]),
        )
        if start_metadata else SessionClock.start(session_id)
    )
    events = UnifiedEventStream(session.context.session_root / "events.jsonl", session_id=session_id, clock=clock)
    display: KmsDisplayBackend | FakeDisplayBackend | None = None
    monitor: LgpioLickMonitor | None = None
    cameras: LocalCameraSupervisor | None = None
    cameras_active = False
    camera_watch_stop = Event()
    camera_watch_thread: Thread | None = None
    camera_failures: list[str] = []
    audio_stop = Event()
    lick_telemetry_stop = Event()
    lick_telemetry_thread: Thread | None = None
    audio_thread: Thread | None = None
    audio_errors: list[str] = []
    audio_latencies_ms: list[float] = []
    audio_request_indices: list[int] = []
    audio_summary: dict[str, Any] = {}
    display_payload: dict[str, Any] | None = None
    camera_commands: tuple[str, ...] = ()
    camera_preview_metadata: dict[str, object] = {"requested": camera_preview, "enabled": False}
    preview_environment: CameraPreviewEnvironment | None = None
    lick_monitor_diagnostics: dict[str, Any] | None = None
    status = "FAILED"
    error: str | None = None
    interrupted = False
    degraded: list[str] = []
    operator_stop = False
    operator_abort = False

    raw_counts = {"lick_left": 0, "lick_right": 0}
    classified_counts = {"lick_left": 0, "lick_right": 0}
    lick_telemetry = LickTelemetryState(
        requested=use_licks, active_level=config.hardware.lick_active_level
    )

    def on_raw(edge: RawLickEdge) -> None:
        raw_counts[edge.channel] += 1
        lick_telemetry.record_edge(edge.channel, edge.level)
        events.emit(
            "LICK_RAW_EDGE",
            source_monotonic_ns=edge.timestamp_ns,
            channel=edge.channel,
            gpio_bcm=edge.bcm_pin,
            level=edge.level,
            raw_edge_index=raw_counts[edge.channel] - 1,
        )

    def on_classified(lick: ClassifiedLick) -> None:
        classified_counts[lick.channel] += 1
        lick_telemetry.record_onset(lick.channel, lick.timestamp_ns)
        events.emit(
            "LICK",
            source_monotonic_ns=lick.timestamp_ns,
            channel=lick.channel,
            gpio_bcm=lick.bcm_pin,
            classified_lick_index=classified_counts[lick.channel] - 1,
            raw_edge_index=lick.raw_edge_index,
        )

    def watch_cameras() -> None:
        while not camera_watch_stop.wait(0.25):
            try:
                statuses = cameras.poll() if cameras is not None else ()
            except Exception as exc:  # noqa: BLE001 — report outside timing path
                camera_failures.append(f"camera watchdog: {exc}")
                return
            for camera_status in statuses:
                if camera_status.state.value == "FAILED":
                    message = f"{camera_status.camera_id}: {camera_status.error or 'camera failed'}"
                    if message not in camera_failures:
                        camera_failures.append(message)
                        events.emit(
                            "CAMERA_FAILURE",
                            source_monotonic_ns=camera_status.stop_monotonic_ns,
                            reason=camera_status.error,
                            **_camera_event_fields(camera_status),
                        )

    try:
        if control is not None:
            def write_control_event(item: dict[str, Any]) -> None:
                fields = item.copy()
                event = fields.pop("event")
                monotonic = fields.pop("monotonic_ns")
                fields.pop("utc_time", None)
                events.emit_reliable(event, source_monotonic_ns=monotonic, **fields)

            control.bind_event_sink(write_control_event)
            write_operator_control_metadata(session.context.session_root, control.provenance())
            control.update_snapshot(
                hardware={
                    "storage": "session_open",
                    "gpio": "monitoring" if use_licks else "not_requested",
                    "audio": "not_requested" if audio is None else "preparing",
                    "irig": "external_not_probed",
                    "chrony": "external_not_probed",
                },
                protocol_state={"phase": "session_start", "planned_frames": plan.total_frames},
            )
        if simulate:
            events.emit(
                "SESSION_START",
                mouse_id=mouse_id,
                protocol="natural-images",
                simulated=True,
                display_backend="simulated",
            )
        else:
            events.emit("SESSION_START", mouse_id=mouse_id, protocol="natural-images")
        events.emit("CLOCK_SYNC", source_monotonic_ns=clock.reference_monotonic_ns, **clock.sync_fields())
        if audio is not None and audio_settings is not None:
            audio_dir = session.context.session_root / "audio"
            audio_dir.mkdir()
            for clip in audio_clips.values():
                shutil.copyfile(PILOT_AUDIO_ASSET_ROOT / clip.filename, audio_dir / clip.filename)
            shutil.copyfile(PILOT_AUDIO_ASSET_ROOT / "manifest.csv", audio_dir / "manifest.csv")
            atomic_write_json(session.context.session_root / "audio_manifest.json", {
                "device_name_match": audio_settings.device_name_match,
                "sample_rate_hz": 48_000,
                "schedule_order": list(audio_settings.sequence),
                "start_delay_s": audio_settings.start_delay_s,
                "interval_s": audio_settings.interval_s,
                "gain_db": audio_settings.gains_db,
                "callback_semantics": "PCM callback start; not physical acoustic onset",
                "stimuli": [
                    {
                        "stimulus_id": clip.stimulus_id,
                        "filename": clip.filename,
                        "sha256": clip.sha256,
                        "sample_rate_hz": clip.sample_rate_hz,
                        "duration_s": clip.duration_s,
                        "gain_db": audio_settings.gains_db[clip.stimulus_id],
                    }
                    for clip in audio_clips.values()
                ],
            })
            atomic_write_json(session.context.session_root / "audio_plan.json", {
                "schema_version": 1,
                "sequence": list(audio_settings.sequence),
                "visual_plan_duration_s": plan.total_frames / config.display.refresh_hz,
                "start_reference": "immediately before KMS sequence dispatch",
                "trials": [
                    {
                        "audio_index": trial.audio_index,
                        "stimulus_id": trial.stimulus_id,
                        "filename": trial.filename,
                        "duration_s": audio_clips[trial.stimulus_id].duration_s,
                        "planned_offset_s": trial.planned_offset_s,
                    }
                    for trial in audio_schedule
                ],
            })
            audio.prepare(audio_clips, audio_settings.gains_db)
            events.emit_reliable(
                "AUDIO_PREPARED",
                device_name_match=audio_settings.device_name_match,
                stimulus_count=len(audio_clips),
                persistent_stream=True,
                preloaded_pcm=True,
            )
            if control is not None:
                control.update_snapshot(hardware={"audio": "prepared"})
        if use_cameras and camera_preview:
            preview_environment = resolve_camera_preview_environment()
            camera_preview_metadata = preview_environment.metadata
            events.emit("CAMERA_PREVIEW_SELECTION", **camera_preview_metadata)
            if not preview_environment.enabled:
                events.emit("CAMERA_PREVIEW_UNAVAILABLE", **camera_preview_metadata)
        session.write_plan(plan)
        resolver = AssetResolver(config.paths.asset_root)
        if manifest is None:
            manifest = build_selected_asset_manifest(
                plan,
                resolver,
                target_width_px=config.display.width_px,
                target_height_px=config.display.height_px,
                transform=str(plan.metadata.get("asset_transform", "crop")),
                background_value=int(plan.metadata.get("background_gray", 127)),
            )
        session.write_asset_manifest(manifest)
        session.write_preflight_report(
            PreflightReport(
                checks=[
                    {"name": "natural_image_assets", "passed": True, "detail": "selected assets resolved"},
                    {"name": "reward", "passed": True, "detail": "disabled for demo"},
                    {"name": "vacuum", "passed": True, "detail": "disabled for demo"},
                    {"name": "gpio_policy", "passed": True, "detail": "only BCM26/27 may be claimed"},
                ]
            )
        )
        session.write_cache_manifest({"bounded": True, "asset_cache_items": 8, "display_queue_items": 32})
        session.write_resource_summary(
            {
                "mode": "natural_image_demo",
                "display_connector": config.display.stimulus_connector,
                **({"simulated": True, "display_backend": "simulated"} if simulate else {}),
                "camera_preview_connector": config.display.preview_connector,
                "camera_preview": camera_preview_metadata,
                "camera_width_px": DEMO_CAMERA_WIDTH,
                "camera_height_px": DEMO_CAMERA_HEIGHT,
                "camera_fps": DEMO_CAMERA_FPS,
                "camera_codec": DEMO_CAMERA_CODEC,
                "rewards_enabled": False,
                "bounded": True,
            }
        )

        if use_licks:
            monitor = LgpioLickMonitor(
                config.hardware,
                on_raw_edge=on_raw,
                on_classified=on_classified,
            )
            monitor.start()
            lick_telemetry.set_available(True)
            for channel, level in monitor.last_level.items():
                lick_telemetry.record_edge(channel, level)
            lick_monitor_diagnostics = monitor.diagnostics()
            events.emit(
                "LICK_MONITOR_READY",
                **monitor.diagnostics(),
                raw_and_classified_streams=True,
            )
            if control is not None:
                def update_lick_telemetry() -> None:
                    while not lick_telemetry_stop.wait(0.5):
                        control.update_snapshot(
                            protocol_state={"lick_state": lick_telemetry.snapshot()}
                        )

                lick_telemetry_thread = Thread(
                    target=update_lick_telemetry, name="rpi-vstim-lick-telemetry", daemon=True
                )
                lick_telemetry_thread.start()

        if use_cameras:
            specs, camera_commands = _resolve_camera_specs(
                config,
                session.context.session_root,
                preview=camera_preview,
                preview_environment=preview_environment,
                enumerate_cameras=enumerate_cameras,
            )
            cameras = LocalCameraSupervisor(
                specs,
                session_root=session.context.session_root,
                verify_output_growth=config.cameras.verify_output_growth,
            )
            for spec in specs:
                events.emit(
                    "CAMERA_START_REQUEST",
                    camera_id=spec.camera_id,
                    camera_role=spec.role,
                    stable_device_identifier=spec.stable_device_identifier,
                    requested_selector=spec.resolved_camera.runtime_selector if spec.resolved_camera else "",
                    width=spec.requested_width_px,
                    height=spec.requested_height_px,
                    fps=spec.requested_fps,
                    codec=spec.pixel_format_or_codec,
                    recording_path=str(
                        (
                            session.context.session_root
                            / "camera"
                            / spec.camera_id
                            / f"capture.{spec.output_extension}"
                        ).relative_to(
                            session.context.session_root
                        )
                    ),
                    preview_enabled=spec.preview_enabled,
                    preview_geometry=spec.preview_geometry,
                    preview_connector=spec.preview_connector,
                    command=list(spec.command),
                )
            cameras.start(session.context.session_root)
            cameras_active = True
            camera_manifest = cameras.manifest()
            if control is not None:
                control.update_snapshot(hardware={
                    f"camera_{index + 1}": str(item.get("state", "RECORDING")).lower()
                    for index, item in enumerate(camera_manifest)
                })
            for camera_status in camera_manifest:
                events.emit("CAMERA_READY", **camera_status)
                if camera_status.get("preview_enabled"):
                    events.emit("CAMERA_PREVIEW_READY", verification="process_started", **camera_status)
            camera_watch_thread = Thread(target=watch_cameras, name="rpi-vstim-camera-watch", daemon=True)
            camera_watch_thread.start()

        if simulate:
            display = FakeDisplayBackend()
        else:
            display = KmsDisplayBackend(native_binary=native_binary, use_lease=True)
            display.photodiode = PhotodiodePatch(
                config.photodiode.corner,
                config.photodiode.size_px,
                config.photodiode.on_value,
                config.photodiode.off_value,
            )
        display.open(config.display)
        if control is not None:
            control.update_snapshot(hardware={"display": "simulated" if simulate else "acquiring"})
        renderer = getattr(display, "renderer", None)
        if not simulate and renderer is None:
            raise NaturalImageDemoError("KMS display did not provide a frame renderer")
        preparer = AssetPreparer(
            resolver,
            config.display.width_px,
            config.display.height_px,
            transform=str(plan.metadata.get("asset_transform", "crop")),
            background_value=int(plan.metadata.get("background_gray", 127)),
            cache_size=8,
            manifest=manifest,
        )
        gray = bytes([int(plan.metadata.get("background_gray", 127))]) * (
            config.display.width_px * config.display.height_px * 3
        )

        def frame_stream():
            nonlocal operator_stop, operator_abort
            frame_index = 0
            producer_sequence = 0
            for planned in plan.events:
                if control is not None and frame_index and (control.stop_requested or control.abort_requested):
                    operator_stop = control.stop_requested
                    operator_abort = control.abort_requested
                    audio_stop.set()
                    break
                if audio_errors:
                    raise NaturalImageDemoError(
                        f"audio coexistence failed: {audio_errors[0]}"
                    )
                if planned.kind == "image":
                    image_filename = str(planned.metadata["image"])
                    image_id = Path(image_filename).stem
                    image_index = None
                    suffix = image_id.rsplit("_", 1)[-1]
                    if suffix.isdecimal():
                        image_index = int(suffix)
                    phase, stimulus_kind = "TASK", "natural_image"
                else:
                    image_filename = image_id = None
                    image_index = None
                    phase = "PRE" if planned.event_id == "initial-gray" else (
                        "POST" if planned.event_id == "final-gray" else
                        "ITI" if planned.kind == "iti" else planned.phase
                    )
                    stimulus_kind = "gray"
                if control is not None:
                    control.update_snapshot(protocol_state={
                        "stimulus_state": {
                            "phase": phase,
                            "stimulus_kind": stimulus_kind,
                            "image_id": image_id,
                            "image_index": image_index,
                            "image_filename": image_filename,
                            "sequence_index": int(planned.trial_id) if planned.trial_id else None,
                        }
                    })
                if planned.kind == "image":
                    prepared = preparer.prepare(str(planned.metadata["image"]))
                    rgb888 = prepared.rgb888
                    asset_key = prepared.asset_key
                else:
                    rgb888 = gray
                    asset_key = "gray:127"
                payload = (
                    rgb888
                    if simulate
                    else renderer.prepare_payload(
                        rgb888,
                        photodiode_state=planned.photodiode,
                        asset_key=asset_key,
                    )
                )
                for _ in range(planned.frame_count):
                    if simulate and frame_index:
                        time.sleep(1.0 / config.display.refresh_hz)
                    if control is not None and frame_index and (control.stop_requested or control.abort_requested):
                        operator_stop = control.stop_requested
                        operator_abort = control.abort_requested
                        audio_stop.set()
                        return
                    yield DisplaySequenceFrame(
                        DisplaySequenceMetadata(
                            logical_frame_index=frame_index,
                            event_id=planned.event_id,
                            sequence_id=planned.sequence_id or planned.event_id,
                            asset_key=asset_key,
                            photodiode_state=planned.photodiode,
                            payload_size=len(payload),
                            producer_sequence=producer_sequence,
                        ),
                        payload,
                    )
                    frame_index += 1
                    producer_sequence += 1

        events.emit(
            "SIMULATED_DISPLAY_REQUEST" if simulate else "DISPLAY_ACQUIRE_REQUEST",
            display_backend="simulated" if simulate else "kms",
            connector=config.display.stimulus_connector,
            ownership="none" if simulate else "lease",
            width=config.display.width_px,
            height=config.display.height_px,
            refresh_hz=config.display.refresh_hz,
            pixel_format=config.display.pixel_format,
            total_frames=plan.total_frames,
        )
        if audio is not None and audio_settings is not None:
            audio_start_ns = time.monotonic_ns()
            events.emit_reliable(
                "AV_ACQUISITION_START",
                source_monotonic_ns=audio_start_ns,
                audio_schedule_start_monotonic_ns=audio_start_ns,
                planned_visual_duration_s=plan.total_frames / config.display.refresh_hz,
            )

            def run_audio_schedule() -> None:
                try:
                    _play_coexistence_audio(
                        audio,
                        audio_schedule,
                        events,
                        clock,
                        audio_start_ns,
                        audio_stop,
                        audio_latencies_ms,
                        audio_request_indices,
                        audio_errors,
                    )
                except Exception as exc:  # noqa: BLE001 - let the main thread finalize the session.
                    audio_errors.append(f"audio scheduler: {exc}")

            audio_thread = Thread(
                target=run_audio_schedule, name="rpi-vstim-audio-schedule", daemon=True
            )
            audio_thread.start()
        display_payload = display.present_sequence(frame_stream())
        if simulate:
            display_payload.update(
                simulated=True,
                display_backend="simulated",
                timing_source="simulation_count_only",
                physical_kms_trace=False,
            )
        if control is not None:
            control.mark_finishing()
        operator_stop = operator_stop or bool(control and control.stop_requested)
        operator_abort = operator_abort or bool(control and control.abort_requested)
        display_payload["planned_frame_count"] = plan.total_frames
        display_payload["operator_stopped_early"] = operator_stop
        display_payload["operator_aborted"] = operator_abort
        if control is not None:
            control.update_snapshot(
                hardware={"audio": "active" if audio is not None else "not_requested"},
                protocol_state={
                    "phase": "finishing",
                    "planned_frames": plan.total_frames,
                    "completed_frames": display_payload.get("completed_frame_count", 0),
                },
            )
        if audio_thread is not None:
            audio_thread.join(timeout=10.0)
            if audio_thread.is_alive():
                audio_stop.set()
                raise NaturalImageDemoError("audio schedule did not finish after KMS presentation")
            if audio_errors:
                raise NaturalImageDemoError(f"audio coexistence failed: {audio_errors[0]}")
        if not simulate:
            first_callback = display_payload.get("first_page_flip_callback_monotonic_ns")
            events.emit(
                "DISPLAY_ACQUIRED",
                source_monotonic_ns=int(first_callback) if first_callback else None,
                connector=display_payload.get("connector"),
                ownership=display_payload.get("ownership"),
                lease_objects=display_payload.get("lease_objects"),
                modeset_count=display_payload.get("ownership_lifecycle", {}).get("modeset_count"),
            )
        _emit_display_boundary_events(
            events,
            plan,
            display_payload,
            manifest=manifest,
            refresh_hz=config.display.refresh_hz,
        )
        if not simulate:
            events.emit(
                "DISPLAY_RELEASED",
                source_monotonic_ns=display_payload.get("last_page_flip_callback_monotonic_ns") or None,
                restored=display_payload.get("restored"),
                ownership_lifecycle=display_payload.get("ownership_lifecycle"),
            )
        session.write_display_result(display_payload)
        if camera_failures:
            raise NaturalImageDemoError("required camera failed during demo: " + "; ".join(camera_failures))
        if operator_abort:
            status = "ABORTED"
            error = "operator requested abort"
            events.emit_reliable("SESSION_ABORTED", reason="operator", request=control.provenance().get("abort"))
        else:
            status = "COMPLETE"
            if operator_stop:
                events.emit_reliable("SESSION_STOPPED", reason="operator", request=control.provenance().get("stop"))
    except KeyboardInterrupt:
        interrupted = True
        status = "INTERRUPTED"
        error = "operator interrupted session"
        events.emit("SESSION_INTERRUPTED", reason="SIGINT")
    except Exception as exc:  # noqa: BLE001 — preserve artifacts on demo failure
        status = "FAILED"
        error = str(exc)
        events.emit("SESSION_FAILURE", error=error)
    finally:
        if audio is not None and audio_settings is not None:
            audio_stop.set()
            if audio_thread is not None:
                audio_thread.join(timeout=10.0)
                if audio_thread.is_alive():
                    audio_errors.append("audio scheduler did not stop before cleanup deadline")
            if audio_errors and status == "COMPLETE":
                status = "FAILED"
                error = "audio coexistence failed: " + "; ".join(audio_errors)
            try:
                audio_summary = _audio_summary(
                    audio.diagnostics(), audio_schedule, audio_request_indices,
                    audio_latencies_ms, audio_errors, audio_settings,
                )
                events.emit_reliable("AUDIO_SUMMARY", **audio_summary)
                atomic_write_json(session.context.session_root / "audio_summary.json", audio_summary)
            except Exception as exc:  # noqa: BLE001 - retain remaining session cleanup.
                degraded.append(f"audio diagnostics: {exc}")
                if status == "COMPLETE":
                    status = "FAILED"
                    error = str(exc)
            try:
                audio.close()
            except Exception as exc:  # noqa: BLE001 - preserve cleanup diagnostics.
                degraded.append(f"audio cleanup: {exc}")
                if status == "COMPLETE":
                    status = "FAILED"
                    error = str(exc)
        if display is not None:
            try:
                display.close()
            except Exception as exc:  # noqa: BLE001 — preserve cleanup diagnostics
                degraded.append(f"display cleanup: {exc}")
        if monitor is not None:
            try:
                lick_monitor_diagnostics = monitor.diagnostics()
                events.emit("LICK_MONITOR_STATUS", **lick_monitor_diagnostics)
                monitor.stop()
                lick_telemetry.set_available(False)
                events.emit("LICK_MONITOR_STOPPED", **monitor.diagnostics())
            except Exception as exc:  # noqa: BLE001 — preserve cleanup diagnostics
                lick_telemetry.set_available(False)
                degraded.append(f"lick cleanup: {exc}")
        lick_telemetry_stop.set()
        if lick_telemetry_thread is not None:
            lick_telemetry_thread.join(timeout=1.0)
        camera_watch_stop.set()
        if camera_watch_thread is not None:
            camera_watch_thread.join(timeout=2.0)
        if cameras_active and cameras is not None:
            try:
                scientific_interval, coverage_timing_source = _scientific_display_interval(display_payload)
                statuses = cameras.stop(
                    scientific_interval_monotonic_ns=scientific_interval,
                    coverage_timing_source=coverage_timing_source,
                )
                if control is not None:
                    control.update_snapshot(hardware={
                        f"camera_{index + 1}": status.state.value.lower()
                        for index, status in enumerate(statuses)
                    })
                for camera_status in statuses:
                    events.emit(
                        "CAMERA_STOP",
                        source_monotonic_ns=camera_status.stop_monotonic_ns,
                        **_camera_event_fields(camera_status),
                        stop_monotonic_ns=camera_status.stop_monotonic_ns,
                        stop_utc_ns=camera_status.stop_utc_ns,
                        bytes_written=camera_status.bytes_written,
                        exit_status=camera_status.exit_status,
                        verification_state=camera_status.verification_state,
                        failure_reason=camera_status.error,
                    )
                    if camera_status.state == CameraState.FAILED:
                        message = f"{camera_status.camera_id}: {camera_status.error or 'camera failed'}"
                        if message not in camera_failures:
                            camera_failures.append(message)
                    elif camera_status.state == CameraState.DEGRADED:
                        degraded.append(
                            f"optional camera {camera_status.camera_id}: "
                            f"{camera_status.error or camera_status.verification_error or 'degraded'}"
                        )
            except Exception as exc:  # noqa: BLE001 — continue finalization
                degraded.append(f"camera cleanup: {exc}")
        if camera_failures and "camera" not in degraded:
            degraded.append("camera")
        if camera_failures and status == "COMPLETE":
            status = "FAILED"
            error = "required camera failed: " + "; ".join(camera_failures)
        events.emit("SESSION_END", status=status, error=error, interrupted=interrupted)
        try:
            event_diagnostics = events.close()
        except Exception as exc:  # noqa: BLE001 — preserve final status
            event_diagnostics = events.diagnostics() | {"close_error": str(exc)}
            degraded.append(f"event writer cleanup: {exc}")
        if control is not None:
            control.update_snapshot(
                hardware={
                    "display": "simulated" if simulate else "released",
                    "storage": "finalizing",
                    "gpio": "closed" if use_licks else "not_requested",
                    "audio": "closed" if audio is not None else "not_requested",
                },
                integrity={
                    "event_drops": event_diagnostics.get("dropped_count", 0),
                    "writer_errors": event_diagnostics.get("error_count", 0),
                    "kms_completed": 0 if simulate else (display_payload or {}).get("completed_frame_count", 0),
                    **(
                        {"simulated_frames_completed": (display_payload or {}).get("completed_frame_count", 0)}
                        if simulate else {}
                    ),
                    "camera_errors": len(camera_failures),
                },
                protocol_state={"phase": status.lower()},
            )
        if event_diagnostics["error_count"] or event_diagnostics["dropped_count"]:
            status = "FAILED"
            error = (
                f"event log integrity failure: {event_diagnostics['dropped_count']} dropped, "
                f"{event_diagnostics['error_count']} writer errors"
            )
            degraded.append("event log")
        camera_manifest = cameras.manifest() if cameras is not None else []
        try:
            session.update_status(
                status,
                lifecycle=status,
                error=error,
                degraded=degraded,
                cleanup_errors=degraded,
            )
            session.close()
        except Exception as exc:  # noqa: BLE001 — preserve best-effort final files
            degraded.append(f"session finalization: {exc}")
        if control is not None:
            control.update_snapshot(hardware={"storage": "finalized"})
            control.update_snapshot(protocol_state={
                "lick_state": lick_telemetry.snapshot(),
                "stimulus_state": {
                    "phase": status, "stimulus_kind": "gray", "image_id": None,
                    "image_index": None, "image_filename": None, "sequence_index": None,
                },
            })
        _write_demo_metadata(
            session.context.session_root,
            mouse_id=mouse_id,
            event_diagnostics=event_diagnostics,
            status=status,
            error=error,
            raw_counts=raw_counts,
            classified_counts=classified_counts,
            camera_manifest=camera_manifest,
            camera_commands=camera_commands,
            lick_monitor_diagnostics=lick_monitor_diagnostics,
            camera_preview=camera_preview_metadata,
            audio_summary=audio_summary,
            operator_control=control.provenance() if control is not None else None,
            simulated=simulate,
        )
        if control is not None:
            control.bind_event_sink(lambda _item: None)

    return NaturalImageDemoResult(
        session.context.session_root,
        status,
        error,
        raw_counts,
        classified_counts,
        camera_manifest,
        event_diagnostics,
        display_payload,
        camera_preview_metadata,
        audio_summary,
    )
