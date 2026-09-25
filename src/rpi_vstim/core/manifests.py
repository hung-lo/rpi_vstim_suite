from __future__ import annotations

from pathlib import Path
from typing import Any

from .session import atomic_write_json


def write_manifest(path: Path, values: dict[str, Any]) -> None:
    atomic_write_json(path, values)

