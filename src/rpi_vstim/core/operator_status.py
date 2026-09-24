from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorStatus:
    phase: str = "CREATED"
    message: str = "Phase 00 skeleton"

