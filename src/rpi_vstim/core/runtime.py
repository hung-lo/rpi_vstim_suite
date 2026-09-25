from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from rpi_vstim.core.camera import CameraStartupError, FakeLocalCameraService
from rpi_vstim.core.config import Config
from rpi_vstim.core.lifecycle import Lifecycle, LifecycleState, RuntimeServices
from rpi_vstim.core.session import SessionOutput, new_session
from rpi_vstim.display.fake import FakeDisplayBackend
from rpi_vstim.hardware.worker import SimulatedHardwareWorker
from rpi_vstim.protocols.natural_images import NaturalImageSettings, build_plan as build_natural_plan
from rpi_vstim.protocols.reward_conditioning import (
    RewardConditioningSettings,
    RewardPhase,
    build_plan as build_reward_plan,
)
from rpi_vstim.telemetry.payloads import TelemetryMessage
from rpi_vstim.telemetry.publisher import InMemoryTelemetryPublisher


class SimulationInterrupted(RuntimeError):
    pass


class TelemetryRequiredError(RuntimeError):
    pass


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
) -> RuntimeServices:
    return RuntimeServices(
        display=FakeDisplayBackend(),
        hardware=SimulatedHardwareWorker(),
        cameras=FakeLocalCameraService(config.cameras, fail_ids=set(camera_failures)),
        telemetry=InMemoryTelemetryPublisher(fail=telemetry_failure),
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
        return build_reward_plan(settings)
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
) -> SimulationResult:
    simulation_session = replace(
        config.session,
        experimental=False,
        simulation=True,
    )
    simulation_display = replace(config.display, backend="fake")
    config = replace(config, session=simulation_session, display=simulation_display)
    session = new_session(config, protocol_name=protocol_name, session_id=session_id, seed=seed)
    session.write_initial_outputs()
    plan = plan or build_simulation_plan(config, protocol_name=protocol_name, seed=seed)
    session.write_plan(plan)
    services = build_simulated_services(
        config,
        camera_failures=camera_failures,
        telemetry_failure=telemetry_failure,
    )
    lifecycle = services.lifecycle
    degraded: list[str] = []
    error: str | None = None
    sequence_number = 0

    def transition(state: LifecycleState) -> None:
        nonlocal sequence_number
        lifecycle.transition(state)
        session.update_status(state.value, lifecycle=state.value, degraded=degraded)
        session.record_event(state.value, lifecycle=state.value)
        sequence_number += 1
        if not services.telemetry.publish(TelemetryMessage(
            message_type="lifecycle",
            session_id=session.context.session_id,
            protocol=session.context.protocol_name,
            lifecycle=state.value,
            sequence_number=sequence_number,
            degraded=list(degraded),
        )):
            if config.telemetry.required:
                raise TelemetryRequiredError("required telemetry publisher failed")
            if "telemetry" not in degraded:
                degraded.append("telemetry")

    try:
        transition(LifecycleState.CONFIGURED)
        transition(LifecycleState.PREFLIGHT)
        services.display.open(config.display)
        services.hardware.start()
        try:
            services.cameras.start(session.context.session_root)
        except CameraStartupError:
            raise
        if services.cameras.degraded:
            degraded.append("camera")
        transition(LifecycleState.PREPARING)
        transition(LifecycleState.PRE)
        if interrupt:
            raise SimulationInterrupted("simulated interruption")
        if protocol_failure:
            raise RuntimeError("simulated protocol failure")
        for event in plan.events:
            target_lifecycle = {
                "PRE": LifecycleState.PRE,
                "TASK": LifecycleState.TASK,
                "POST": LifecycleState.POST,
            }.get(event.phase, LifecycleState.TASK)
            if lifecycle.state != target_lifecycle:
                transition(target_lifecycle)
            color = (255, 255, 255) if event.photodiode == "on" else (127, 127, 127)
            services.display.present_color(color, frames=max(1, event.frame_count))
            session.record_event(
                "PLAN_EVENT",
                lifecycle=target_lifecycle.value,
                sequence_id=event.sequence_id or event.event_id,
                detail=event.kind,
            )
            sequence_number += 1
            services.telemetry.publish(TelemetryMessage(
                message_type="trial" if event.trial_id else "state",
                session_id=session.context.session_id,
                protocol=session.context.protocol_name,
                lifecycle=target_lifecycle.value,
                sequence_number=sequence_number,
                trial_id=event.trial_id,
                stimulus=event.metadata.get("image"),
                cameras=services.cameras.manifest(),
                degraded=list(degraded),
            ))
        transition(LifecycleState.FINALIZING)
        transition(LifecycleState.COMPLETE)
    except SimulationInterrupted as exc:
        error = str(exc)
        lifecycle.state = LifecycleState.INTERRUPTED
    except Exception as exc:
        error = str(exc)
        lifecycle.state = LifecycleState.FAILED
    finally:
        try:
            services.hardware.backend.safe()
            services.hardware.backend.stop()
            services.cameras.stop()
            services.display.close()
            services.telemetry.close()
        except Exception as cleanup_error:
            error = str(cleanup_error)
            lifecycle.state = LifecycleState.CLEANUP_FAILED
        session.update_status(
            lifecycle.state.value,
            lifecycle=lifecycle.state.value,
            error=error,
            degraded=degraded,
        )
        session.record_event(
            "SESSION_FINISHED",
            lifecycle=lifecycle.state.value,
            detail=error or "",
        )
        session.close()
    return SimulationResult(session, services, lifecycle.state, degraded, error)
