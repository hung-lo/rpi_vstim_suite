"""Atomic, engine-owned lifecycle snapshots for supervisor recovery."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class ControlStateFile:
    """Write complete JSON snapshots without replacing an existing launch file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._created = False
        self._lock = threading.Lock()

    def write(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        with self._lock:
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            try:
                os.fchmod(descriptor, 0o600)
                stream = os.fdopen(descriptor, "w", encoding="utf-8")
                descriptor = -1
                with stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self._created:
                    os.replace(temporary, self.path)
                else:
                    # link() makes the first state visible atomically and refuses stale paths.
                    try:
                        os.link(temporary, self.path)
                    except FileExistsError:
                        raise FileExistsError(
                            f"control state file already exists; use a unique path: {self.path}"
                        ) from None
                    self._created = True
                    os.unlink(temporary)
                directory = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
