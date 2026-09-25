import pytest

from rpi_vstim.core.lifecycle import Lifecycle, LifecycleState


@pytest.mark.parametrize(
    "terminal_state",
    [
        LifecycleState.COMPLETE,
        LifecycleState.INCOMPLETE,
        LifecycleState.INTERRUPTED,
        LifecycleState.FAILED,
        LifecycleState.CLEANUP_FAILED,
    ],
)
def test_terminal_lifecycle_states_cannot_transition(terminal_state):
    lifecycle = Lifecycle()
    lifecycle.state = terminal_state
    with pytest.raises(RuntimeError, match="terminal"):
        lifecycle.transition(LifecycleState.TASK)
