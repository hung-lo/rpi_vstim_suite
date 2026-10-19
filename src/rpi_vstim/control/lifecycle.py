"""Generic experiment lifecycle for supervisor-controlled runs."""

from __future__ import annotations

from enum import StrEnum


class ExperimentState(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    RUNNING = "RUNNING"
    FINISHING = "FINISHING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    ABORTED = "ABORTED"


_TRANSITIONS = {
    ExperimentState.PREPARING: {ExperimentState.READY, ExperimentState.ERROR, ExperimentState.ABORTED},
    ExperimentState.READY: {ExperimentState.RUNNING, ExperimentState.ERROR, ExperimentState.ABORTED},
    ExperimentState.RUNNING: {ExperimentState.FINISHING, ExperimentState.ERROR, ExperimentState.ABORTED},
    ExperimentState.FINISHING: {ExperimentState.COMPLETE, ExperimentState.ERROR, ExperimentState.ABORTED},
    ExperimentState.COMPLETE: set(),
    ExperimentState.ERROR: set(),
    ExperimentState.ABORTED: set(),
}


class LifecycleError(ValueError):
    """Raised when a lifecycle transition is not allowed."""


class ExperimentLifecycle:
    def __init__(self) -> None:
        self._state = ExperimentState.PREPARING

    @property
    def state(self) -> ExperimentState:
        return self._state

    def validate_transition(self, state: ExperimentState) -> None:
        if state not in _TRANSITIONS[self._state]:
            raise LifecycleError(f"invalid lifecycle transition: {self._state} -> {state}")

    def transition(self, state: ExperimentState) -> None:
        self.validate_transition(state)
        self._state = state
