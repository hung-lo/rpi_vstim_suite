from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PreflightReport:
    passed: bool = True
    checks: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        self.passed = self.passed and passed

