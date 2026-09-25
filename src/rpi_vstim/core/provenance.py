from __future__ import annotations

import os
import platform
import sys

from .timestamps import utc_ns


def resolve_source_commit() -> str:
    return os.environ.get("RPI_VSTIM_SOURCE_COMMIT", "unknown")


def collect_provenance(*, source_commit: str | None = None) -> dict[str, object]:
    source_commit = source_commit if source_commit is not None else resolve_source_commit()
    return {
        "created_utc_ns": utc_ns(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "repository_commit": source_commit,
        "phase": "00",
    }
