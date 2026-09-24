from __future__ import annotations

from typing import Protocol


class ExperimentProtocol(Protocol):
    name: str
    version: str

    def build_plan(self, settings: object) -> object: ...
    def run(self, plan: object, runtime: object) -> object: ...

