class ProtocolPlaceholder:
    """Structural placeholder shared by all Phase 00 protocol families."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.version = "placeholder"

    def build_plan(self, settings: object = None) -> None:
        raise NotImplementedError(f"{self.name} is not implemented in Phase 00")

    def run(self, plan: object, runtime: object) -> None:
        raise NotImplementedError(f"{self.name} is not implemented in Phase 00")

