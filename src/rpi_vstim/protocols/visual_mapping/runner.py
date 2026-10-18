from __future__ import annotations

import csv
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

from rpi_vstim.camera import (
    CameraCaptureSpec,
    CameraIdentity,
    LocalCameraSupervisor,
    build_rpicam_command,
    enumerate_rpicam_cameras,
    resolve_camera_identities,
)
from rpi_vstim.core.config import Config, ConfigError
from rpi_vstim.core.preflight import PreflightReport
from rpi_vstim.core.session import atomic_write_json, new_session
from rpi_vstim.core.unified_events import SessionClock, UnifiedEventStream
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.display.kms import KmsDisplayBackend
from rpi_vstim.display.photodiode import PhotodiodePatch
from rpi_vstim.display.transport import DisplaySequenceFrame, DisplaySequenceMetadata
from rpi_vstim.protocols.visual_mapping.config import validate_refresh_rate

from .cache import FrameCache, cache_key_for, open_frame_cache
from .geometry import geometry_snapshot

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30.0


class VisualMappingRunError(RuntimeError):
    """A visual-mapping session could not complete safely."""


@dataclass(frozen=True)
class VisualMappingResult:
    session_root: Path
    status: str
    error: str | None
    event_diagnostics: dict[str, Any]
    display_payload: dict[str, Any] | None
    camera_manifest: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETE"


def packed_frame_size(config: Config) -> int:
    bytes_per_pixel = {"RGB565": 2, "XRGB8888": 4}.get(config.display.pixel_format)
    if bytes_per_pixel is None:
        raise ConfigError(f"unsupported display pixel format {config.display.pixel_format}")
    return config.display.width_px * config.display.height_px * bytes_per_pixel


def validate_cache(
    config: Config,
    protocol_name: str,
    settings: Any,
    cache_root: Path,
) -> FrameCache:
    if protocol_name == "drifting-gratings":
        from rpi_vstim.protocols.drifting_gratings.cache import render_settings
    elif protocol_name == "retinotopy":
        from rpi_vstim.protocols.retinotopy.cache import render_settings
    else:
        raise ValueError(f"unsupported visual-mapping protocol {protocol_name!r}")
    values = render_settings(config, settings)
    size = packed_frame_size(config)
    key = cache_key_for(protocol_name, values, size)
    return open_frame_cache(
        Path(cache_root) / protocol_name / key,
        protocol=protocol_name,
        cache_key=key,
        frame_size_bytes=size,
        render_settings=values,
    )


def _resolve_cameras(config: Config, session_root: Path, enumerate_cameras: Callable):
    if len(config.cameras.devices) != 2:
        raise ConfigError("visual-mapping camera acquisition requires two configured local cameras")
    available = enumerate_cameras()
    configured = tuple(
        CameraIdentity(item.id, item.stable_device_identifier, item.expected_family)
        for item in config.cameras.devices
    )
    report = resolve_camera_identities(configured, available)
    if not report.passed:
        raise VisualMappingRunError(f"camera identity resolution failed: {report.as_dict()}")
    resolved = {camera.camera_id: camera for camera in report.resolved}
    specs: list[CameraCaptureSpec] = []
    commands: list[list[str]] = []
    for device in config.cameras.devices:
        camera = resolved[device.id]
        spec = CameraCaptureSpec(
            camera_id=device.id,
            role=device.role,
            stable_device_identifier=device.stable_device_identifier,
            required=True,
            backend=device.backend,
            command=(),
            output_extension="mp4",
            requested_width_px=CAMERA_WIDTH,
            requested_height_px=CAMERA_HEIGHT,
            requested_fps=CAMERA_FPS,
            pixel_format_or_codec="h264",
            startup_timeout_s=device.startup_timeout_s,
            stop_timeout_s=device.stop_timeout_s,
            stall_timeout_s=device.stall_timeout_s,
            resolved_camera=camera,
        )
        output = session_root / "camera" / device.id / "capture.mp4"
        command = build_rpicam_command(spec, output, resolved_camera=camera)
        spec = replace(spec, command=command)
        specs.append(spec)
        commands.append(list(command))
    return tuple(specs), commands


def _display_interval(payload: dict[str, Any] | None):
    if not payload:
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


def _frame_event_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["frame_index"]): item
        for item in payload.get("flip_events", [])
        if isinstance(item, dict) and "frame_index" in item
    }


def _trace_time(item: dict[str, Any] | None, payload: dict[str, Any]) -> int | None:
    if not item:
        return None
    if payload.get("kernel_timestamp_clock") == "monotonic" and item.get("kernel_event_ns"):
        return int(item["kernel_event_ns"])
    if item.get("callback_monotonic_ns"):
        return int(item["callback_monotonic_ns"])
    return None


def _write_trial_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _event_rows(protocol_name: str, plan: Any, cache: FrameCache) -> list[dict[str, Any]]:
    manifest_sets = cache.manifest["frame_sets"]
    rows: list[dict[str, Any]] = []
    if protocol_name == "drifting-gratings":
        following_itis = {
            event.trial_id: event
            for event in plan.events
            if event.kind == "iti"
        }
        for event in plan.events:
            if event.kind != "drifting-grating":
                continue
            orientation_id = int(event.metadata["orientation_id"])
            cache_set = f"orientation_{orientation_id:02d}"
            iti = following_itis.get(event.trial_id)
            rows.append({
                "event_id": event.event_id,
                "trial_index": int(event.trial_id or 0),
                "orientation_id": orientation_id,
                "bar_orientation_deg": event.metadata["bar_orientation_deg"],
                "drift_direction_deg": event.metadata["drift_direction_deg"],
                "repeat_number": event.metadata["repeat_number"],
                "starting_phase_deg": event.metadata["starting_phase_deg"],
                "temporal_frequency_hz": event.metadata["temporal_frequency_hz"],
                "spatial_frequency": event.metadata["spatial_frequency_cycles_per_cm"],
                "spatial_frequency_units": "cycles_per_cm",
                "contrast": event.metadata.get("contrast", 1.0),
                "mean_luminance": event.metadata.get("mean_luminance", 0.5),
                "stimulus_frame_count": event.frame_count,
                "planned_stimulus_duration_s": event.frame_count / plan.metadata.get("refresh_hz", 60.0),
                "planned_start_frame": event.planned_start_frame,
                "requested_iti_s": iti.metadata.get("requested_iti_s") if iti else "",
                "planned_iti_s": iti.metadata.get("planned_iti_s") if iti else "",
                "cache_key": cache.cache_key,
                "cache_frame_set": cache_set,
                "cache_sha256": manifest_sets[cache_set]["sha256"],
            })
    return rows


def _enrich_plan_for_session(protocol_name: str, plan: Any, settings: Any, refresh_hz: float):
    """Keep legacy planner serialization stable; add analysis detail to unified sessions."""
    events = []
    metadata = dict(plan.metadata)
    if protocol_name == "drifting-gratings":
        from rpi_vstim.protocols.drifting_gratings import drift_direction_deg

        trials = [
            (orientation_id, orientation, repeat_number)
            for orientation_id, orientation in enumerate(settings.orientations_deg, start=1)
            for repeat_number in range(1, settings.trials_per_orientation + 1)
        ]
        rng = random.Random(settings.sequence_seed)
        rng.shuffle(trials)
        requested_itis = {
            str(index): settings.iti_base_s + rng.random() * settings.iti_jitter_max_s
            for index in range(1, len(trials) + 1)
        }
        metadata.update({
            "resolved_seed": settings.sequence_seed,
            "refresh_hz": refresh_hz,
            "orientation_semantics": "bar_orientation_deg is bar axis; drift_direction_deg is motion direction",
            "drift_direction_convention": "(bar_orientation_deg - 90) mod 360",
            "spatial_frequency_units": "cycles_per_cm",
            "spatial_frequency_cycles_per_cm": settings.spatial_frequency_cycles_per_cm,
            "temporal_frequency_hz": settings.temporal_frequency_hz,
            "contrast": settings.contrast,
            "mean_luminance": settings.mean_luminance,
        })
        for event in plan.events:
            item = dict(event.metadata)
            if event.kind == "drifting-grating":
                angle = float(item["bar_orientation_deg"])
                item.update({
                    "drift_direction_deg": drift_direction_deg(angle),
                    "spatial_frequency_units": "cycles_per_cm",
                    "contrast": settings.contrast,
                    "mean_luminance": settings.mean_luminance,
                    "rectangular_patch_geometry": (
                        vars(settings.rectangular_patch_geometry)
                        if settings.rectangular_patch_geometry is not None else None
                    ),
                    "orientation_semantics": "bar_orientation_deg is bar axis; drift_direction_deg is motion direction",
                    "stimulus_frame_count": event.frame_count,
                    "planned_stimulus_duration_s": event.frame_count / refresh_hz,
                })
            elif event.kind == "iti":
                requested = requested_itis[str(event.trial_id)]
                item.update({
                    "requested_iti_s": requested,
                    "planned_iti_s": event.frame_count / refresh_hz,
                    "frame_quantized": True,
                })
            events.append(replace(event, metadata=item))
    else:
        from rpi_vstim.protocols.retinotopy import refreshes_per_source_frame

        source_count = round(settings.sweep_duration_s * settings.movement_frame_rate_hz)
        refresh_counts = list(refreshes_per_source_frame(
            source_count, refresh_hz, settings.movement_frame_rate_hz
        ))
        metadata.update({
            "enabled_directions": list(settings.enabled_directions),
            "repeats_per_direction": settings.repeats_per_direction,
            "sequence_order_mode": settings.sequence_order_mode,
            "resolved_seed": settings.sequence_seed,
            "movement_frame_rate_hz": settings.movement_frame_rate_hz,
            "nominal_refresh_hz": refresh_hz,
            "source_frame_count": source_count,
            "screen_motion_model": "linear in screen pixels; not warped for visual angle",
        })
        for event in plan.events:
            item = dict(event.metadata)
            if event.kind == "retinotopy-sweep":
                item.update({
                    "source_frame_count": source_count,
                    "movement_frame_rate_hz": settings.movement_frame_rate_hz,
                    "refreshes_per_source_frame": refresh_counts,
                    "planned_sweep_duration_s": event.frame_count / refresh_hz,
                })
            events.append(replace(event, metadata=item))
    return replace(plan, events=tuple(events), metadata=metadata)


def run_visual_mapping(
    config: Config,
    *,
    protocol_name: str,
    settings: Any,
    session_id: str,
    seed: int,
    cache_root: Path,
    use_cameras: bool = False,
    simulate: bool = False,
    native_binary: Path | str | None = None,
    enumerate_cameras: Callable = enumerate_rpicam_cameras,
    display_factory: Callable[[], Any] | None = None,
    camera_supervisor_factory: Callable[..., Any] = LocalCameraSupervisor,
) -> VisualMappingResult:
    if protocol_name == "drifting-gratings":
        from rpi_vstim.protocols.drifting_gratings import build_plan
    elif protocol_name == "retinotopy":
        from rpi_vstim.protocols.retinotopy import build_plan
    else:
        raise ValueError(f"unsupported visual-mapping protocol {protocol_name!r}")
    config.validate()
    validate_refresh_rate(config, settings)
    configured_seed = getattr(settings, "sequence_seed", seed)
    if configured_seed != seed:
        raise ConfigError(
            f"session seed {seed} does not match protocol sequence seed {configured_seed}"
        )
    if simulate and use_cameras:
        raise ConfigError("simulation mode cannot acquire physical cameras")
    if simulate:
        config = replace(config, display=replace(config.display, backend="fake"))
    elif config.display.backend != "kms" or config.display.ownership != "lease":
        raise ConfigError("hardware visual-mapping runs require the configured leased KMS display")
    if use_cameras and not config.cameras.devices:
        raise ConfigError("--cameras requires camera devices in the rig profile")
    plan = _enrich_plan_for_session(
        protocol_name, build_plan(settings), settings, config.display.refresh_hz
    )
    cache = validate_cache(config, protocol_name, settings, cache_root)
    configured = replace(
        config,
        protocol=replace(
            config.protocol,
            name=protocol_name,
            version="unified-0.1",
            parameters={key: value for key, value in vars(settings).items() if key != "refresh_hz"},
        ),
    )
    session = new_session(configured, protocol_name=protocol_name, session_id=session_id, seed=seed)
    session.write_initial_outputs()
    clock = SessionClock.start(session_id)
    events = UnifiedEventStream(
        session.context.session_root / "events.jsonl", session_id=session_id, clock=clock
    )
    display = display_factory() if display_factory else (
        FakeDisplayBackend() if simulate else KmsDisplayBackend(native_binary=native_binary, use_lease=True)
    )
    cameras = None
    cameras_active = False
    camera_watch_stop = Event()
    camera_watch_thread: Thread | None = None
    camera_failures: list[str] = []
    camera_commands: list[list[str]] = []
    camera_manifest: list[dict[str, Any]] = []
    display_payload: dict[str, Any] | None = None
    status = "FAILED"
    error: str | None = None
    cleanup_errors: list[str] = []
    event_diagnostics: dict[str, Any] = {}
    frame_rows: list[dict[str, Any]] = []
    request_ns: int | None = None

    try:
        events.emit_reliable("SESSION_START", protocol=protocol_name, seed=seed)
        events.emit_reliable(
            "CLOCK_SYNC", source_monotonic_ns=clock.reference_monotonic_ns, **clock.sync_fields()
        )
        plan_value = plan.as_dict()
        plan_value["metadata"].update({
            "source_commit": session.context.source_commit,
            "render_cache_key": cache.cache_key,
            "screen_geometry": geometry_snapshot(configured),
            "display_timestamps_are_not_physical_onset": True,
        })
        for event_value in plan_value["events"]:
            if event_value["kind"] == "drifting-grating":
                set_name = f"orientation_{int(event_value['metadata']['orientation_id']):02d}"
                event_value["metadata"].update({
                    "cache_key": cache.cache_key,
                    "cache_frame_set": set_name,
                    "cache_sha256": cache.manifest["frame_sets"][set_name]["sha256"],
                })
            elif event_value["kind"] == "retinotopy-sweep":
                from rpi_vstim.protocols.retinotopy import DIRECTIONS

                set_name = DIRECTIONS[str(event_value["metadata"]["direction"])].movement_axis
                event_value["metadata"].update({
                    "cache_key": cache.cache_key,
                    "cache_frame_set": set_name,
                    "cache_sha256": cache.manifest["frame_sets"][set_name]["sha256"],
                })
        session.write_plan(plan_value)
        session.write_cache_manifest({
            "bounded": True,
            "protocol": protocol_name,
            "cache_key": cache.cache_key,
            "cache_path": str(cache.path),
            "render_settings": cache.manifest["render_settings"],
            "frame_sets": cache.manifest["frame_sets"],
            "artifacts": cache.manifest["artifacts"],
        })
        session.write_preflight_report(PreflightReport(checks=[
            {"name": "render_cache", "passed": True, "detail": cache.cache_key},
            {"name": "gpio_outputs", "passed": True, "detail": "no GPIO outputs acquired"},
            {"name": "simulation", "passed": True, "detail": "fake display" if simulate else "hardware path"},
        ]))
        session.write_resource_summary({
            "mode": "visual_mapping_simulation" if simulate else "visual_mapping_hardware",
            "protocol": protocol_name,
            "display_connector": configured.display.stimulus_connector,
            "camera_count": 2 if use_cameras else 0,
            "cache_key": cache.cache_key,
            "rewards_enabled": False,
            "vacuum_enabled": False,
            "airpuff_enabled": False,
            "gpio_outputs_acquired": False,
        })
        if protocol_name == "retinotopy":
            from rpi_vstim.protocols.retinotopy.sequence import (
                build_frame_plan_rows,
                write_frame_plan,
            )
            frame_rows = build_frame_plan_rows(configured, settings, plan, cache=cache)
            write_frame_plan(session.context.session_root / "retinotopy_frame_plan.csv", frame_rows)
            atomic_write_json(session.context.session_root / "screen_geometry.json", geometry_snapshot(configured))
        else:
            trial_rows = _event_rows(protocol_name, plan, cache)
            _write_trial_csv(session.context.session_root / "drifting_grating_trial_plan.csv", trial_rows)
        if use_cameras:
            specs, camera_commands = _resolve_cameras(configured, session.context.session_root, enumerate_cameras)
            cameras = camera_supervisor_factory(
                specs,
                session_root=session.context.session_root,
                verify_output_growth=configured.cameras.verify_output_growth,
            )
            cameras.start(session.context.session_root)
            cameras_active = True
            for camera in cameras.manifest():
                events.emit_reliable("CAMERA_READY", **camera)

            def watch_cameras() -> None:
                while not camera_watch_stop.wait(0.25):
                    try:
                        current_statuses = cameras.poll()
                    except Exception as exc:  # noqa: BLE001 - propagate watchdog failure to acquisition
                        camera_failures.append(f"camera watchdog: {exc}")
                        events.emit_reliable("CAMERA_WATCHDOG_FAILURE", error=str(exc))
                        return
                    for camera_status in current_statuses:
                        if camera_status.required and camera_status.state.value == "FAILED":
                            message = f"{camera_status.camera_id}: {camera_status.error or 'camera failed'}"
                            if message not in camera_failures:
                                camera_failures.append(message)
                                events.emit_reliable(
                                    "CAMERA_FAILURE",
                                    source_monotonic_ns=camera_status.stop_monotonic_ns,
                                    camera_id=camera_status.camera_id,
                                    error=camera_status.error,
                                )
                            return

            camera_watch_thread = Thread(target=watch_cameras, name="rpi-vstim-visual-map-camera-watch", daemon=True)
            camera_watch_thread.start()

        display.photodiode = PhotodiodePatch(
            configured.photodiode.corner,
            configured.photodiode.size_px,
            configured.photodiode.on_value if configured.photodiode.enabled else configured.photodiode.off_value,
            configured.photodiode.off_value,
        )
        display.open(configured.display)
        request_ns = time.monotonic_ns()
        events.emit_reliable(
            "DISPLAY_ACQUIRE_REQUEST",
            source_monotonic_ns=request_ns,
            connector=configured.display.stimulus_connector,
            ownership=configured.display.ownership,
            total_frames=plan.total_frames,
            cache_key=cache.cache_key,
        )

        def frame_stream():
            logical_frame = 0
            for planned in plan.events:
                if camera_failures:
                    raise VisualMappingRunError(camera_failures[0])
                if planned.kind == "drifting-grating":
                    set_name = f"orientation_{int(planned.metadata['orientation_id']):02d}"
                    for index in range(planned.frame_count):
                        payload = cache.read_frame(set_name, index)
                        yield DisplaySequenceFrame(
                            DisplaySequenceMetadata(logical_frame, planned.event_id, planned.sequence_id or planned.event_id,
                                f"{set_name}:{index}", "on", len(payload), logical_frame), payload
                        )
                        logical_frame += 1
                elif planned.kind == "retinotopy-sweep":
                    from rpi_vstim.protocols.retinotopy import DIRECTIONS

                    direction = str(planned.metadata["direction"])
                    definition = DIRECTIONS[direction]
                    set_name = definition.movement_axis
                    counts = planned.metadata["refreshes_per_source_frame"]
                    for source_index, refresh_count in enumerate(counts):
                        cache_index = (
                            source_index
                            if definition.sign > 0
                            else len(counts) - 1 - source_index
                        )
                        payload = cache.read_frame(set_name, cache_index)
                        for _ in range(refresh_count):
                            yield DisplaySequenceFrame(
                                DisplaySequenceMetadata(logical_frame, planned.event_id, set_name,
                                    f"{direction}:{source_index}", "on", len(payload), logical_frame), payload
                            )
                            logical_frame += 1
                else:
                    payload = cache.read_frame("gray", 0)
                    for _ in range(planned.frame_count):
                        yield DisplaySequenceFrame(
                            DisplaySequenceMetadata(logical_frame, planned.event_id, planned.event_id,
                                "gray:127", "off", len(payload), logical_frame), payload
                        )
                        logical_frame += 1

        display_payload = display.present_sequence(frame_stream())
        if int(display_payload.get("completed_frame_count", -1)) != plan.total_frames:
            raise VisualMappingRunError("display completed a different frame count than planned")
        if not simulate:
            if display_payload.get("aborted"):
                raise VisualMappingRunError("KMS presentation reported an aborted sequence")
            if display_payload.get("restored") is not True:
                raise VisualMappingRunError("KMS display ownership was not restored cleanly")
            if display_payload.get("flip_trace_truncated"):
                raise VisualMappingRunError("KMS flip trace was truncated; session cannot be marked complete")
            if not display_payload.get("frame_index_contiguous", False):
                raise VisualMappingRunError("KMS trace frame indices are not contiguous")
            if int(display_payload.get("flip_events_stored", -1)) != plan.total_frames:
                raise VisualMappingRunError("KMS result did not retain every planned flip event")
        events_by_frame = _frame_event_map(display_payload)
        for planned in plan.events:
            if planned.kind not in {"drifting-grating", "retinotopy-sweep"}:
                continue
            start_index = planned.planned_start_frame
            end_index = start_index + planned.frame_count - 1
            first = events_by_frame.get(start_index)
            last = events_by_frame.get(end_index)
            first_ns = _trace_time(first, display_payload)
            last_ns = _trace_time(last, display_payload)
            planned_onset_ns = request_ns + round(
                start_index / configured.display.refresh_hz * 1_000_000_000
            )
            fields = {
                "protocol_event_id": planned.event_id,
                "trial_index": planned.trial_id,
                "condition": planned.sequence_id,
                "planned_onset_frame": start_index,
                "planned_onset_s": start_index / configured.display.refresh_hz,
                "planned_onset_monotonic_ns": planned_onset_ns,
                "planned_onset_utc_ns": clock.fields(planned_onset_ns)["utc_ns"],
                "stimulus_frame_count": planned.frame_count,
                "display_sequence_request_monotonic_ns": request_ns,
                "display_sequence_request_utc_ns": clock.fields(request_ns)["utc_ns"],
                "actual_first_kms_monotonic_ns": first_ns,
                "actual_last_kms_monotonic_ns": last_ns,
                "actual_first_kms_utc_ns": clock.fields(first_ns)["utc_ns"] if first_ns else None,
                "actual_last_kms_utc_ns": clock.fields(last_ns)["utc_ns"] if last_ns else None,
                "kms_trace_first_frame_index": start_index,
                "kms_trace_last_frame_index": end_index,
                "timing_semantics": "one KMS sequence request plus per-boundary KMS timing; not photodiode-measured physical onset",
                **planned.metadata,
            }
            events.emit_reliable(
                "STIMULUS_PRESENTATION_START",
                source_monotonic_ns=first_ns or request_ns,
                **fields,
            )
            events.emit_reliable(
                "STIMULUS_PRESENTATION_END",
                source_monotonic_ns=last_ns or request_ns,
                protocol_event_id=planned.event_id,
                trial_index=planned.trial_id,
                actual_last_kms_monotonic_ns=last_ns,
                kms_trace_last_frame_index=end_index,
            )
        if protocol_name == "retinotopy":
            from rpi_vstim.protocols.retinotopy.sequence import (
                update_actual_kms_mapping,
                write_frame_plan,
            )
            update_actual_kms_mapping(frame_rows, display_payload.get("flip_events", []))
            write_frame_plan(session.context.session_root / "retinotopy_frame_plan.csv", frame_rows)
        session.write_display_result(display_payload)
        atomic_write_json(session.context.session_root / "kms_timing_trace.json", display_payload)
        events.emit_reliable(
            "DISPLAY_TRACE_COMPLETE",
            source_monotonic_ns=display_payload.get("last_page_flip_callback_monotonic_ns"),
            completed_frame_count=display_payload.get("completed_frame_count"),
            missed_vblank_count=display_payload.get("missed_vblank_count"),
            estimated_dropped_frame_count=display_payload.get("estimated_dropped_frame_count"),
        )
        if camera_failures:
            raise VisualMappingRunError("required camera failed: " + "; ".join(camera_failures))
        if use_cameras:
            camera_interval, timing_source = _display_interval(display_payload)
            statuses = cameras.stop(
                scientific_interval_monotonic_ns=camera_interval,
                coverage_timing_source=timing_source,
            )
            cameras_active = False
            camera_manifest = [item.as_dict() for item in statuses]
            if any(item.required and item.state.value != "STOPPED" for item in statuses):
                raise VisualMappingRunError("one or more required cameras failed finalization")
            atomic_write_json(
                session.context.session_root / "visual_mapping_camera_commands.json",
                {"commands": camera_commands},
            )
        status = "COMPLETE"
    except KeyboardInterrupt:
        status, error = "INTERRUPTED", "operator interrupted session"
        events.emit_reliable("SESSION_INTERRUPTED", reason="SIGINT")
    except Exception as exc:  # noqa: BLE001 - preserve an incomplete session after any runtime failure
        status, error = "FAILED", str(exc)
        try:
            events.emit_reliable("SESSION_FAILURE", error=error)
        except Exception as emit_exc:  # noqa: BLE001 - the original failure remains authoritative
            cleanup_errors.append(f"failure event logging: {emit_exc}")
    finally:
        camera_watch_stop.set()
        if camera_watch_thread is not None:
            camera_watch_thread.join(timeout=2.0)
            if camera_watch_thread.is_alive():
                cleanup_errors.append("camera watchdog did not stop cleanly")
        if cameras_active and cameras is not None:
            try:
                interval, source = _display_interval(display_payload)
                statuses = cameras.stop(
                    scientific_interval_monotonic_ns=interval,
                    coverage_timing_source=source,
                )
                camera_manifest = [item.as_dict() for item in statuses]
                if any(item.required and item.state.value != "STOPPED" for item in statuses):
                    cleanup_errors.append("required camera finalization failed")
            except Exception as exc:  # noqa: BLE001 - continue releasing remaining services
                cleanup_errors.append(f"camera cleanup: {exc}")
        try:
            display.close()
        except Exception as exc:  # noqa: BLE001 - continue session finalization
            cleanup_errors.append(f"display cleanup: {exc}")
        try:
            events.emit_reliable("SESSION_END", status=status, error=error)
            event_diagnostics = events.close()
        except Exception as exc:  # noqa: BLE001 - retain remaining cleanup diagnostics
            event_diagnostics = events.diagnostics() | {"close_error": str(exc)}
            cleanup_errors.append(f"event writer cleanup: {exc}")
        if event_diagnostics.get("dropped_count", 0) or event_diagnostics.get("error_count", 0):
            status = "FAILED"
            error = "unified event writer reported dropped events or errors"
        if cleanup_errors:
            status = "FAILED"
            error = error or "; ".join(cleanup_errors)
        try:
            cache.close()
        except Exception as exc:  # noqa: BLE001 - cache handles must not prevent session closure
            cleanup_errors.append(f"render cache cleanup: {exc}")
            status = "FAILED"
            error = error or str(exc)
        summary_path = session.context.session_root / "visual_mapping_summary.json"
        summary = {
            "protocol": protocol_name,
            "status": status,
            "error": error,
            "seed": seed,
            "cache_key": cache.cache_key,
            "source_commit": session.context.source_commit,
            "event_diagnostics": event_diagnostics,
            "camera_manifest": camera_manifest,
            "display_requested_frame_count": plan.total_frames,
            "display_completed_frame_count": (
                display_payload.get("completed_frame_count") if display_payload else None
            ),
            "camera_commands": camera_commands,
        }
        try:
            atomic_write_json(summary_path, summary)
        except Exception as exc:  # noqa: BLE001 - a missing summary invalidates completion
            cleanup_errors.append(f"visual mapping summary: {exc}")
            status = "FAILED"
            error = error or str(exc)
            summary.update(status=status, error=error)
            try:
                atomic_write_json(summary_path, summary)
            except Exception as retry_exc:  # noqa: BLE001 - retain failure in session status
                cleanup_errors.append(f"visual mapping failure summary: {retry_exc}")
        if cleanup_errors:
            status = "FAILED"
            error = error or "; ".join(cleanup_errors)
            summary.update(status=status, error=error)
            try:
                atomic_write_json(summary_path, summary)
            except Exception as exc:  # noqa: BLE001 - retain the original failure and note artifact failure
                cleanup_errors.append(f"visual mapping summary update: {exc}")
        try:
            session.update_status(
                status,
                lifecycle=status,
                error=error,
                degraded=cleanup_errors,
                cleanup_errors=cleanup_errors,
            )
        except Exception as exc:  # noqa: BLE001 - report best-effort session finalization failure
            cleanup_errors.append(f"session finalization: {exc}")
            status = "FAILED"
            error = error or str(exc)
        try:
            session.close()
        except Exception as exc:  # noqa: BLE001 - preserve best-effort session cleanup
            cleanup_errors.append(f"session close: {exc}")
            status = "FAILED"
            error = error or str(exc)
        if status != summary["status"]:
            summary.update(status=status, error=error)
            try:
                atomic_write_json(summary_path, summary)
            except Exception as exc:  # noqa: BLE001 - the session status remains authoritative
                cleanup_errors.append(f"visual mapping final summary update: {exc}")
    return VisualMappingResult(
        session.context.session_root,
        status,
        error,
        event_diagnostics,
        display_payload,
        camera_manifest,
    )
