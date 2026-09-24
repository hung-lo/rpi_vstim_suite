from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    completed: int = 0
    total: int = 0

