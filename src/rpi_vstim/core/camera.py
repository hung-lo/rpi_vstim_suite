from __future__ import annotations


class CameraBackend:
    """Import-safe camera boundary; acquisition is intentionally not implemented."""

    def start(self) -> None:
        raise NotImplementedError("camera acquisition starts in a later phase")

    def stop(self) -> None:
        raise NotImplementedError("camera acquisition starts in a later phase")

