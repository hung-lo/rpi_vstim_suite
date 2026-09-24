from __future__ import annotations

from .simulated import SimulatedHardwareBackend


class SimulatedHardwareWorker:
    """Synchronous worker-shaped facade used until the spawned Pi worker exists."""

    def __init__(self) -> None:
        self.backend = SimulatedHardwareBackend()

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

