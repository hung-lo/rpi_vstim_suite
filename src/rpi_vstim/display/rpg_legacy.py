"""Optional legacy adapter boundary; it is never imported at module import time."""


class RpgLegacyBackend:
    name = "rpg_legacy"

    def open(self, config):
        raise NotImplementedError("legacy RPG adapter is not part of Phase 00")

