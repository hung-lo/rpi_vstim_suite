import pytest

from rpi_vstim.hardware.contract import (
    BoundedHardwareCommandQueue,
    HardwareCommand,
    HardwareCommandKind,
)
from rpi_vstim.hardware.worker import SimulatedHardwareWorker


def test_hardware_commands_are_bounded_idempotent_and_water_limited():
    queue = BoundedHardwareCommandQueue(1)
    reward = HardwareCommand("reward-1", HardwareCommandKind.REWARD, volume_ul=5)
    queue.put(reward)
    with pytest.raises(BufferError):
        queue.put(HardwareCommand("reward-2", HardwareCommandKind.REWARD))

    worker = SimulatedHardwareWorker()
    worker.maximum_water_ul = 5
    assert worker.execute_command(reward).event == "REWARD_REQUESTED"
    assert worker.execute_command(reward).event == "DUPLICATE_IGNORED"
    with pytest.raises(ValueError, match="water safeguard"):
        worker.execute_command(HardwareCommand("reward-2", HardwareCommandKind.REWARD, volume_ul=1))
