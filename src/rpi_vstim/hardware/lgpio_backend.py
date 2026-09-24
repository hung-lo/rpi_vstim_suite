"""Lazy placeholder for the explicit lgpio/GPIO Zero backend."""


class LgpioBackend:
    def start(self):
        raise NotImplementedError("lgpio backend starts after Phase 00")

