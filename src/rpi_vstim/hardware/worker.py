from __future__ import annotations

from .contract import HardwareCommand, HardwareCommandKind, HardwareEvent
from .simulated import SimulatedHardwareBackend


class SimulatedHardwareWorker:
    """Synchronous worker-shaped facade used until the spawned Pi worker exists."""

    def __init__(self) -> None:
        self.backend = SimulatedHardwareBackend()
        self.maximum_water_ul = 0
        self.delivered_water_ul = 0
        self._handled_commands: set[str] = set()

    def start(self):
        return self.backend.start()

    def execute(self, command: str) -> dict[str, object]:
        if command == "SAFE":
            self.backend.safe()
            return {"event": "OUTPUTS_SAFE"}
        if command == "SHUTDOWN":
            self.backend.stop()
            return {"event": "WORKER_STOPPED"}
        return {"event": "SIMULATED", "command": command}

    def execute_command(self, command: HardwareCommand) -> HardwareEvent:
        if command.command_id in self._handled_commands:
            return HardwareEvent(command.command_id, "DUPLICATE_IGNORED", self.backend.outputs_safe)
        self._handled_commands.add(command.command_id)
        if command.kind == HardwareCommandKind.SAFE:
            self.backend.safe()
            return HardwareEvent(command.command_id, "OUTPUTS_SAFE", True)
        if command.kind == HardwareCommandKind.SHUTDOWN:
            self.backend.stop()
            return HardwareEvent(command.command_id, "WORKER_STOPPED", True)
        if command.kind == HardwareCommandKind.REWARD:
            if self.maximum_water_ul and self.delivered_water_ul + command.volume_ul > self.maximum_water_ul:
                raise ValueError("water safeguard limit exceeded")
            self.delivered_water_ul += command.volume_ul
            return HardwareEvent(command.command_id, "REWARD_REQUESTED", self.backend.outputs_safe, command.volume_ul)
        if command.kind == HardwareCommandKind.SUCTION:
            return HardwareEvent(command.command_id, "SUCTION_REQUESTED", self.backend.outputs_safe)
        raise ValueError(f"unsupported hardware command: {command.kind}")
