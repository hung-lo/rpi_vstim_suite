from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


class EventLogger:
    """Small CSV logger; protocol-specific columns are added by later phases."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None
        self._writer = None

    def open(self, fieldnames: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=fieldnames)
        self._writer.writeheader()

    def write(self, row: dict[str, Any]) -> None:
        if self._writer is None:
            raise RuntimeError("event logger is not open")
        self._writer.writerow(row)
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
            self._writer = None

