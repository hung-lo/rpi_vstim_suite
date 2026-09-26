from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from rpi_vstim.core.camera import CameraStartupError, FakeLocalCameraService
from rpi_vstim.core.config import Config
from rpi_vstim.core.lifecycle import LifecycleState, RuntimeServices
from rpi_vstim.core.session import SessionOutput, new_session
from rpi_vstim.core.assets import AssetResolver, build_selected_asset_manifest
from rpi_vstim.core.preflight import PreflightReport
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.hardware.worker import SimulatedHardwareWorker
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan as build_natural_plan
from rpi_vstim.protocols.drifting_gratings import (
    DEFAULT_ORIENTATIONS_DEG,
    DriftingGratingSettings,
    build_plan as build_grating_plan,
)
from rpi_vstim.protocols.retinotopy import RetinotopySettings, build_plan as build_retinotopy_plan
from rpi_vstim.protocols.reward_conditioning import (
    AssignmentStore,
    PhaseStateStore,
    RewardConditioningSettings,
    RewardPhase,
    build_plan as build_reward_plan,
)
from rpi_vstim.telemetry.payloads import TelemetryMessage
from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher
from rpi_vstim.protocols.spout_training import (
    SpoutTrainingSettings,
    build_plan as build_spout_plan,
)


class SimulationInterrupted(RuntimeError):
    pass


class TelemetryRequiredError(RuntimeError):
    pass


class FaultInjectingDisplay:
    def __init__(self, fault: str | None) -> None:
        self.backend = FakeDisplayBackend()
        self.fault = fault
        self.present_count = 0

    def open(self, config):
        if self.fault == "display_consumer_start":
            raise RuntimeError("injected display consumer startup failure")
        return self.backend.open(config)

    def present_color(self, rgb, *, frames):
        if self.fault == "display_consumer_mid" and self.present_count >= 1:
            raise RuntimeError("injected display consumer mid-session failure")
        self.present_count += 1
        return self.backend.present_color(rgb, frames=frames)

    def close(self):
        self.backend.close()
        if self.fault == "cleanup":
            raise RuntimeError("injected display cleanup failure")


@dataclass
class SimulationResult:
    session: SessionOutput
    services: RuntimeServices
    final_state: LifecycleState
    degraded: list[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.final_state == LifecycleState.COMPLETE


def build_simulated_services(
    config: Config,
    *,
    camera_failures: Iterable[str] = (),
    telemetry_failure: bool = False,
    telemetry_fail_after: int | None = None,
    fault: str | None = None,
) -> RuntimeServices:
    return RuntimeServices(
        display=FaultInjectingDisplay(fault) if fault else FakeDisplayBackend(),
        hardware=SimulatedHardwareWorker(),
        cameras=FakeLocalCameraService(config.cameras, fail_ids=set(camera_failures)),
        telemetry=InMemoryTelemetryPublisher(
            fail=telemetry_failure, fail_after=telemetry_fail_after
        ),
    )


def build_simulation_plan(config: Config, *, protocol_name: str | None, seed: int):
    """Build a bounded virtual plan without requiring assets or hardware."""
    name = protocol_name or config.protocol.name
    parameters = config.protocol.parameters
    if name == "natural-images":
        images = tuple(parameters.get("images", (f"natural_image_{index:04d}.png" for index in range(14))))
        settings = NaturalImageSettings(
            images=images,
            seed=seed,
            trial_count=parameters.get("trial_count"),
            image_count=parameters.get("image_count", 5),
            repeat_count=parameters.get("repeat_count", 2),
            selection_seed=parameters.get("selection_seed", 777),
            refresh_hz=config.display.refresh_hz,
            image_duration_s=parameters.get("image_duration_s", 0.5),
            iti_frames=tuple(parameters.get("iti_frames", (42, 60))),
            initial_gray_frames=parameters.get("initial_gray_frames", 180),
            final_gray_frames=parameters.get("final_gray_frames", 180),
            compatibility_profile=parameters.get("compatibility_profile", "natural_legacy_plain"),
            camera_ids=tuple(device.id for device in config.cameras.devices),
        )
        return build_natural_plan(settings)
    if name == "reward-conditioning":
        images = tuple(parameters.get("images", (f"reward_image_{index:02d}.png" for index in range(14))))
        settings = RewardConditioningSettings(
            mouse_id=str(parameters.get("mouse_id", "simulation-mouse")),
            image_pool=images,
            seed=seed,
            blocks=int(parameters.get("blocks", 10)),
            trial_frames=int(parameters.get("trial_frames", 90)),
            reward_boundary_frames=int(parameters.get("reward_boundary_frames", 60)),
            phase=RewardPhase(parameters.get("phase", "acquisition")),
        )
        if settings.blocks < 1 or settings.blocks % 10:
            raise ValueError("blocks must be a positive multiple of 10")
        if settings.trial_frames < 1 or not 0 <= settings.reward_boundary_frames <= settings.trial_frames:
            raise ValueError("invalid reward timing settings")
        if len(set(images)) < 14:
            raise ValueError("reward conditioning requires at least 14 images")
        state_root = config.paths.output_root / ".simulation_reward_state"
        assignment = AssignmentStore(state_root).load_or_create(
            settings.mouse_id, images, seed=20260804
        )
        phase_state = PhaseStateStore(state_root).load_or_create(settings.mouse_id)
        return build_reward_plan(settings, assignment, phase_state)
    if name == "spout-training":
        return build_spout_plan(SpoutTrainingSettings(
            max_rewards=int(parameters.get("max_rewards", 60)),
            interval_min_s=float(parameters.get("interval_min_s", 8.0)),
            interval_max_s=float(parameters.get("interval_max_s", 12.0)),
            criterion_window=int(parameters.get("criterion_window", 20)),
            criterion_min_rewards=int(parameters.get("criterion_min_rewards", 20)),
            criterion_fraction=float(parameters.get("criterion_fraction", 0.8)),
            reward_volume_ul=float(parameters.get("reward_volume_ul", 5.0)),
            suction_delay_s=float(parameters.get("suction_delay_s", 2.5)),
            refresh_hz=config.display.refresh_hz,
            seed=seed,
        ))
    if name == "drifting-gratings":
        return build_grating_plan(DriftingGratingSettings(
            orientations_deg=tuple(parameters.get("orientations_deg", DEFAULT_ORIENTATIONS_DEG)),
            trials_per_orientation=int(parameters.get("trials_per_orientation", 2)),
            stim_duration_s=float(parameters.get("stim_duration_s", 0.5)),
            iti_base_s=float(parameters.get("iti_base_s", 0.7)),
            iti_jitter_max_s=float(parameters.get("iti_jitter_max_s", 0.5)),
            temporal_frequency_hz=float(parameters.get("temporal_frequency_hz", 2.0)),
            spatial_frequency_cycles_per_cm=float(
                parameters.get("spatial_frequency_cycles_per_cm", 0.2)
            ),
            contrast=float(parameters.get("contrast", 1.0)),
            mean_luminance=float(parameters.get("mean_luminance", 0.5)),
            starting_phase_deg=float(parameters.get("starting_phase_deg", 0.0)),
            initial_gray_s=float(parameters.get("initial_gray_s", 3.0)),
            final_gray_s=float(parameters.get("final_gray_s", 3.0)),
            refresh_hz=config.display.refresh_hz,
            sequence_seed=seed,
            grating_mode=str(parameters.get("grating_mode", "fullscreen")),
        ))
    if name == "retinotopy":
        return build_retinotopy_plan(RetinotopySettings(
            sweep_duration_s=float(parameters.get("sweep_duration_s", 20.0)),
            inter_sweep_gray_s=float(parameters.get("inter_sweep_gray_s", 5.0)),
            initial_gray_s=float(parameters.get("initial_gray_s", 3.0)),
            final_gray_s=float(parameters.get("final_gray_s", 3.0)),
            movement_frame_rate_hz=int(parameters.get("movement_frame_rate_hz", 15)),
            bar_width_fraction=float(parameters.get("bar_width_fraction", 0.10)),
            enabled_directions=tuple(
                parameters.get("enabled_directions", ("left_to_right", "top_to_bottom"))
            ),
            repeats_per_direction=int(parameters.get("repeats_per_direction", 1)),
            sequence_order_mode=str(parameters.get("sequence_order_mode", "fixed")),
            refresh_hz=config.display.refresh_hz,
            sequence_seed=seed,
        ))
    raise ValueError(f"simulation is not implemented for protocol: {name}")


def run_simulated_session(
    config: Config,
    *,
    protocol_name: str | None = None,
    session_id: str = "simulation",
    seed: int = 0,
    plan: Any = None,
    camera_failures: Iterable[str] = (),
    telemetry_failure: bool = False,
    interrupt: bool = False,
    protocol_failure: bool = False,
    telemetry_fail_after: int | None = None,
    services: RuntimeServices | None = None,
    fault: str | None = None,
) -> SimulationResult:
    selected_protocol = protocol_name or config.protocol.name
    if selected_protocol != config.protocol.name:
        raise ValueError(
            f"protocol/config mismatch: selected {selected_protocol!r}, "
            f"configured {config.protocol.name!r}"
        )
    simulation_session = replace(
        config.session,
        experimental=False,
        simulation=True,
    )
    simulation_display = replace(config.display, backend="fake")
    config = replace(config, session=simulation_session, display=simulation_display)
    plan = plan or build_simulation_plan(config, protocol_name=protocol_name, seed=seed)
    services = services or build_simulated_services(
        config,
        camera_failures=camera_failures,
        telemetry_failure=telemetry_failure,
        telemetry_fail_after=telemetry_fail_after,
        fault=fault,
    )
    session = new_session(config, protocol_name=selected_protocol, session_id=session_id, seed=seed)
    session.write_initial_outputs()
    session.write_preflight_report(
        PreflightReport(
            checks=[
                {
                    "name": "simulation_mode",
                    "passed": True,
                    "detail": "hardware access disabled",
                }
            ]
        )
    )
    session.write_cache_manifest({"bounded": True, "mode": "simulation", "entries": []})
    session.write_resource_summary(
        {
            "mode": "simulation",
            "camera_count": len(config.cameras.devices),
            "bounded_queues": True,
        }
    )
    lifecycle = services.lifecycle
    degraded: list[str] = []
    error: str | None = None
    cleanup_errors: list[str] = []
    sequence_number = 0

    def publish(message: TelemetryMessage) -> None:
        nonlocal degraded
        if services.telemetry.publish(message):
            return
        if config.telemetry.required:
            raise TelemetryRequiredError("required telemetry publisher failed")
        if "telemetry" not in degraded:
            degraded.append("telemetry")

    def transition(state: LifecycleState) -> None:
        nonlocal sequence_number
        lifecycle.transition(state)
        session.update_status(state.value, lifecycle=state.value, degraded=degraded)
        session.record_event(state.value, lifecycle=state.value)
        sequence_number += 1
        publish(TelemetryMessage(
            message_type="lifecycle",
            session_id=session.context.session_id,
            protocol=session.context.protocol_name,
            lifecycle=state.value,
            sequence_number=sequence_number,
            protocol_version=session.context.protocol_version,
            degraded=list(degraded),
        ))

    try:
        session.write_plan(plan)
        if fault == "asset_manifest_creation":
            raise RuntimeError("injected asset_manifest_creation failure")
        if config.paths.asset_root.is_dir():
            selected_manifest = build_selected_asset_manifest(
                plan,
                AssetResolver(config.paths.asset_root),
                target_width_px=config.display.width_px,
                target_height_px=config.display.height_px,
                transform=plan.metadata.get("asset_transform", "fit_pad"),
                background_value=int(plan.metadata.get("background_gray", 127)),
            )
            session.write_asset_manifest(selected_manifest)
        if fault == "session_metadata_write":
            raise RuntimeError("injected session metadata failure")
        transition(LifecycleState.CONFIGURED)
        transition(LifecycleState.PREFLIGHT)
        if fault == "storage_low_space":
            raise RuntimeError("injected storage low-space signal")
        services.display.open(config.display)
        services.hardware.start()
        try:
            services.cameras.start(session.context.session_root)
        except CameraStartupError:
            raise
        if services.cameras.degraded:
            degraded.append("camera")
        transition(LifecycleState.PREPARING)
        if fault == "producer_start":
            raise RuntimeError(f"injected {fault} failure")
        transition(LifecycleState.PRE)
        if interrupt:
            raise SimulationInterrupted("simulated interruption")
        if protocol_failure:
            raise RuntimeError("simulated protocol failure")
        for event in plan.events:
            camera_poll = getattr(services.cameras, "poll", None)
            if camera_poll is not None:
                camera_statuses = camera_poll()
                if any(
                    status.required and status.state.value == "FAILED"
                    for status in camera_statuses
                ):
                    raise CameraStartupError("required camera failed during recording")
                if any(status.state.value == "DEGRADED" for status in camera_statuses):
                    if "camera" not in degraded:
                        degraded.append("camera")
            if fault == "producer_mid" and sequence_number > 2:
                raise RuntimeError("injected producer mid-session failure")
            target_lifecycle = LifecycleState(event.phase)
            if lifecycle.state != target_lifecycle:
                transition(target_lifecycle)
            color = (255, 255, 255) if event.photodiode == "on" else (127, 127, 127)
            if event.frame_count:
                session.write_display_result(
                    services.display.present_color(color, frames=event.frame_count)
                )
            session.record_event(
                "PLAN_EVENT",
                lifecycle=target_lifecycle.value,
                sequence_id=event.sequence_id or event.event_id,
                detail=event.kind,
            )
            sequence_number += 1
            publish(TelemetryMessage(
                message_type="trial" if event.trial_id else "lifecycle",
                session_id=session.context.session_id,
                protocol=session.context.protocol_name,
                lifecycle=target_lifecycle.value,
                sequence_number=sequence_number,
                protocol_version=session.context.protocol_version,
                trial_id=event.trial_id,
                stimulus=event.metadata.get("image"),
                cameras=services.cameras.manifest(),
                degraded=list(degraded),
            ))
        if fault == "finalization":
            raise RuntimeError("injected finalization failure")
        transition(LifecycleState.FINALIZING)
        transition(LifecycleState.COMPLETE)
    except SimulationInterrupted as exc:
        error = str(exc)
        lifecycle.state = LifecycleState.INTERRUPTED
    except Exception as exc:
        error = str(exc)
        lifecycle.state = LifecycleState.FAILED
    finally:
        for label, action in (
            ("hardware.safe", services.hardware.backend.safe),
            ("hardware.stop", services.hardware.backend.stop),
            ("cameras.stop", services.cameras.stop),
            ("display.close", services.display.close),
            ("telemetry.close", services.telemetry.close),
        ):
            try:
                action()
            except Exception as cleanup_error:
                cleanup_errors.append(f"{label}: {cleanup_error}")
        if cleanup_errors:
            lifecycle.state = LifecycleState.CLEANUP_FAILED
            if error is None:
                error = "cleanup failed"
        try:
            session.update_status(
                lifecycle.state.value,
                lifecycle=lifecycle.state.value,
                error=error,
                degraded=degraded,
                cleanup_errors=cleanup_errors,
            )
        except Exception as status_error:
            cleanup_errors.append(f"manifest.finalize: {status_error}")
            lifecycle.state = LifecycleState.CLEANUP_FAILED
            if error is None:
                error = "cleanup failed"
        try:
            session.record_event(
                "SESSION_FINISHED",
                lifecycle=lifecycle.state.value,
                detail=error or "",
            )
        except Exception as event_error:
            cleanup_errors.append(f"events.finalize: {event_error}")
        if cleanup_errors:
            try:
                session.update_status(
                    lifecycle.state.value,
                    lifecycle=lifecycle.state.value,
                    error=error,
                    degraded=degraded,
                    cleanup_errors=cleanup_errors,
                )
            except Exception:
                pass
        try:
            session.close()
        except Exception as close_error:
            cleanup_errors.append(f"session.close: {close_error}")
            lifecycle.state = LifecycleState.CLEANUP_FAILED
            if error is None:
                error = "cleanup failed"
            try:
                session.update_status(
                    lifecycle.state.value,
                    lifecycle=lifecycle.state.value,
                    error=error,
                    degraded=degraded,
                    cleanup_errors=cleanup_errors,
                )
            except Exception:
                pass
    return SimulationResult(session, services, lifecycle.state, degraded, error)
