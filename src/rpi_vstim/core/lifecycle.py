from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LifecycleState(StrEnum):
    CREATED = "CREATED"
    CONFIGURED = "CONFIGURED"
    PREFLIGHT = "PREFLIGHT"
    PREPARING = "PREPARING"
    WAITING_FOR_2P = "WAITING_FOR_2P"
    PRE = "PRE"
    TASK = "TASK"
    POST = "POST"
    FINALIZING = "FINALIZING"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


class Lifecycle:
    def __init__(self) -> None:
        self.state = LifecycleState.CREATED

    def transition(self, state: LifecycleState) -> None:
        if self.state in {LifecycleState.COMPLETE, LifecycleState.FAILED, LifecycleState.CLEANUP_FAILED}:
            raise RuntimeError(f"cannot transition from terminal state {self.state}")
        self.state = state


@dataclass
class RuntimeServices:
    display: object | None = None
    hardware: object | None = None
    camera: object | None = None
    telemetry: object | None = None
    lifecycle: Lifecycle = field(default_factory=Lifecycle)


class ExperimentRuntime:
    """Phase 00 ownership shell; it performs no hardware work by itself."""

    def __init__(self, services: RuntimeServices | None = None) -> None:
        self.services = services or RuntimeServices()

    def __enter__(self) -> RuntimeServices:
        return self.services

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None:
            self.services.lifecycle.state = LifecycleState.FAILED
        return False

