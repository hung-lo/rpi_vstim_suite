"""Composition runner for the first real natural-image/lick/camera demo."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Any

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
from rpi_vstim.core.assets import AssetPreparer, AssetResolver, build_selected_asset_manifest
from rpi_vstim.core.camera import CameraState
from rpi_vstim.core.config import Config, ConfigError
from rpi_vstim.core.preflight import PreflightReport
from rpi_vstim.core.session import atomic_write_json, new_session
from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream
from rpi_vstim.display.kms import KmsDisplayBackend
from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.transport import DisplaySequenceFrame, DisplaySequenceMetadata
from rpi_vstim.hardware.lgpio_lick import ClassifiedLick, LgpioLickMonitor, RawLickEdge
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan, discover_images

DEMO_CAMERA_WIDTH = 640
DEMO_CAMERA_HEIGHT = 480
DEMO_CAMERA_FPS = 30.0
DEMO_CAMERA_CODEC = "h264"
DEMO_CAMERA_EXTENSION = "mp4"
DEMO_PREVIEW_GEOMETRIES = ((0, 0, 512, 384), (512, 0, 512, 384))
DEFAULT_DEMO_IMAGE_COUNT = 20


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

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETE"


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


def _emit_display_boundary_events(
    stream: UnifiedEventStream,
    plan: Any,
    payload: dict[str, Any],
    *,
    manifest: Any,
    refresh_hz: float,
) -> None:
    by_name = {entry.relative_path: entry for entry in manifest.entries}
    traces = {
        int(item["frame_index"]): item
        for item in payload.get("flip_events", [])
        if isinstance(item, dict) and "frame_index" in item
    }
    first_callback = payload.get("first_page_flip_callback_monotonic_ns")
    total_frames = int(payload.get("completed_frame_count", plan.total_frames))
    for event in plan.events:
        if not event.frame_count:
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
            stream.emit(
                "IMAGE_ONSET",
                source_monotonic_ns=source,
                image_index=int(event.trial_id or 0),
                filename=filename,
                image_sha256=entry.sha256,
                **fields,
            )
            end_source, end_timing = _trace_timestamp(
                payload,
                event.planned_start_frame + event.frame_count,
                traces=traces,
                fallback_start_ns=int(first_callback) if first_callback else None,
                refresh_hz=refresh_hz,
            )
            stream.emit(
                "IMAGE_OFFSET",
                source_monotonic_ns=end_source,
                image_index=int(event.trial_id or 0),
                filename=filename,
                image_sha256=entry.sha256,
                logical_frame_index=event.planned_start_frame + event.frame_count,
                timing_source=end_timing["timing_source"],
            )
        else:
            stream.emit("GRAY_ONSET", source_monotonic_ns=source, **fields)
    if total_frames:
        stream.emit(
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
            "gpio_used": [26, 27],
            "gpio_untouched": [7, 8, 9, 15, 19, 20, 21, 23, 24, 25],
            "raw_lick_count": raw_counts,
            "classified_lick_count": classified_counts,
            "lick_monitor": lick_monitor_diagnostics,
            "camera_manifest": camera_manifest,
            "camera_commands": list(camera_commands),
            "camera_preview": camera_preview,
            "event_log": event_diagnostics,
        }
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
        atomic_write_json(manifest_path, manifest)


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
    enumerate_cameras: Callable[[], tuple[Any, ...]] = enumerate_rpicam_cameras,
) -> NaturalImageDemoResult:
    validate_demo_config(
        config,
        use_licks=use_licks,
        use_cameras=use_cameras,
        preview=camera_preview,
    )
    plan = build_demo_plan(config, seed=seed, image_count=image_count)
    session = new_session(config, protocol_name="natural-images", session_id=session_id, seed=seed)
    session.write_initial_outputs()
    clock = SessionClock.start(session_id)
    events = UnifiedEventStream(session.context.session_root / "events.jsonl", session_id=session_id, clock=clock)
    display: KmsDisplayBackend | None = None
    monitor: LgpioLickMonitor | None = None
    cameras: LocalCameraSupervisor | None = None
    cameras_active = False
    camera_watch_stop = Event()
    camera_watch_thread: Thread | None = None
    camera_failures: list[str] = []
    display_payload: dict[str, Any] | None = None
    camera_commands: tuple[str, ...] = ()
    camera_preview_metadata: dict[str, object] = {"requested": camera_preview, "enabled": False}
    preview_environment: CameraPreviewEnvironment | None = None
    lick_monitor_diagnostics: dict[str, Any] | None = None
    status = "FAILED"
    error: str | None = None
    interrupted = False
    degraded: list[str] = []

    raw_counts = {"lick_left": 0, "lick_right": 0}
    classified_counts = {"lick_left": 0, "lick_right": 0}

    def on_raw(edge: RawLickEdge) -> None:
        raw_counts[edge.channel] += 1
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
        events.emit("SESSION_START", mouse_id=mouse_id, protocol="natural-images")
        events.emit("CLOCK_SYNC", source_monotonic_ns=clock.reference_monotonic_ns, **clock.sync_fields())
        if use_cameras and camera_preview:
            preview_environment = resolve_camera_preview_environment()
            camera_preview_metadata = preview_environment.metadata
            events.emit("CAMERA_PREVIEW_SELECTION", **camera_preview_metadata)
            if not preview_environment.enabled:
                events.emit("CAMERA_PREVIEW_UNAVAILABLE", **camera_preview_metadata)
        session.write_plan(plan)
        resolver = AssetResolver(config.paths.asset_root)
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
            lick_monitor_diagnostics = monitor.diagnostics()
            events.emit(
                "LICK_MONITOR_READY",
                **monitor.diagnostics(),
                raw_and_classified_streams=True,
            )

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
            for camera_status in cameras.manifest():
                events.emit("CAMERA_READY", **camera_status)
                if camera_status.get("preview_enabled"):
                    events.emit("CAMERA_PREVIEW_READY", verification="process_started", **camera_status)
            camera_watch_thread = Thread(target=watch_cameras, name="rpi-vstim-camera-watch", daemon=True)
            camera_watch_thread.start()

        display = KmsDisplayBackend(native_binary=native_binary, use_lease=True)
        display.photodiode = PhotodiodePatch(
            config.photodiode.corner,
            config.photodiode.size_px,
            config.photodiode.on_value,
            config.photodiode.off_value,
        )
        display.open(config.display)
        if display.renderer is None:
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
            frame_index = 0
            producer_sequence = 0
            for planned in plan.events:
                if planned.kind == "image":
                    prepared = preparer.prepare(str(planned.metadata["image"]))
                    rgb888 = prepared.rgb888
                    asset_key = prepared.asset_key
                else:
                    rgb888 = gray
                    asset_key = "gray:127"
                payload = display.renderer.prepare_payload(
                    rgb888,
                    photodiode_state=planned.photodiode,
                    asset_key=asset_key,
                )
                for _ in range(planned.frame_count):
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
            "DISPLAY_ACQUIRE_REQUEST",
            connector=config.display.stimulus_connector,
            ownership="lease",
            width=config.display.width_px,
            height=config.display.height_px,
            refresh_hz=config.display.refresh_hz,
            pixel_format=config.display.pixel_format,
            total_frames=plan.total_frames,
        )
        display_payload = display.present_sequence(frame_stream())
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
        events.emit(
            "DISPLAY_RELEASED",
            source_monotonic_ns=display_payload.get("last_page_flip_callback_monotonic_ns") or None,
            restored=display_payload.get("restored"),
            ownership_lifecycle=display_payload.get("ownership_lifecycle"),
        )
        session.write_display_result(display_payload)
        if camera_failures:
            raise NaturalImageDemoError("required camera failed during demo: " + "; ".join(camera_failures))
        status = "COMPLETE"
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
                events.emit("LICK_MONITOR_STOPPED", **monitor.diagnostics())
            except Exception as exc:  # noqa: BLE001 — preserve cleanup diagnostics
                degraded.append(f"lick cleanup: {exc}")
        camera_watch_stop.set()
        if camera_watch_thread is not None:
            camera_watch_thread.join(timeout=2.0)
        if cameras_active and cameras is not None:
            try:
                statuses = cameras.stop()
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
        if event_diagnostics["error_count"]:
            status = "FAILED"
            error = f"event log writer failure: {event_diagnostics['writer_error'] or 'unknown error'}"
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
        )

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
    )
