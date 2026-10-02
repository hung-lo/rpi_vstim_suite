from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from .timestamps import utc_ns


def resolve_source_commit() -> str:
    if value := os.environ.get("RPI_VSTIM_SOURCE_COMMIT"):
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect_provenance(*, source_commit: str | None = None) -> dict[str, object]:
    source_commit = source_commit if source_commit is not None else resolve_source_commit()
    return {
        "schema_version": 1,
        "data_format_version": "phase4-v1",
        "created_utc_ns": utc_ns(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "repository_commit": source_commit,
        "phase": "00",
    }
