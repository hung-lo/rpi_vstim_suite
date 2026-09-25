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
    if plan is not None:
        session.write_plan(plan)
    services = build_simulated_services(
        config,
        camera_failures=camera_failures,
        telemetry_failure=telemetry_failure,
    )
    lifecycle = services.lifecycle
    degraded: list[str] = []
    error: str | None = None

    def transition(state: LifecycleState) -> None:
        lifecycle.transition(state)
        session.update_status(state.value, lifecycle=state.value, degraded=degraded)
        session.record_event(state.value, lifecycle=state.value)
        if not services.telemetry.publish(
            {"event": "lifecycle", "state": state.value, "session_id": session.context.session_id}
        ):
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
        services.display.present_color((0, 0, 0), frames=1)
        if interrupt:
            raise SimulationInterrupted("simulated interruption")
        if protocol_failure:
            raise RuntimeError("simulated protocol failure")
        transition(LifecycleState.TASK)
        services.display.present_color((128, 128, 128), frames=1)
        session.record_event("TASK_PRESENTED", lifecycle=LifecycleState.TASK.value, sequence_id="simulation-0")
        transition(LifecycleState.POST)
        services.display.present_color((0, 0, 0), frames=1)
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
