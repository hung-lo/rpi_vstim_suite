from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .provenance import collect_provenance
from .timestamps import monotonic_ns, utc_ns

_SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    protocol_name: str
    protocol_version: str
    session_root: Path
    created_utc_ns: int
    created_monotonic_ns: int
    resolved_config: dict[str, Any]
    random_seeds: dict[str, int]
    source_commit: str
    host_provenance: dict[str, Any]


class SessionOutput:
    def __init__(self, context: SessionContext) -> None:
        self.context = context

    def write_initial_outputs(self) -> None:
        self.context.session_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.context.session_root / "resolved_config.json", self.context.resolved_config)
        atomic_write_json(self.context.session_root / "provenance.json", self.context.host_provenance)
        atomic_write_json(
            self.context.session_root / "session_manifest.json",
            {
                "session_id": self.context.session_id,
                "protocol": self.context.protocol_name,
                "protocol_version": self.context.protocol_version,
                "created_utc_ns": self.context.created_utc_ns,
                "status": "CREATED",
                "phase": "00",
            },
        )


def new_session(config: Config, *, protocol_name: str | None = None, session_id: str = "phase00-simulation", seed: int = 0) -> SessionOutput:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("session_id contains unsupported characters")
    protocol = protocol_name or config.protocol.name
    context = SessionContext(
        session_id=session_id,
        protocol_name=protocol,
        protocol_version=config.protocol.version,
        session_root=config.paths.output_root / session_id,
        created_utc_ns=utc_ns(),
        created_monotonic_ns=monotonic_ns(),
        resolved_config=config.as_dict(),
        random_seeds={"protocol": seed},
        source_commit=os.environ.get("RPI_VSTIM_SOURCE_COMMIT", "unknown"),
        host_provenance=collect_provenance(),
    )
    return SessionOutput(context)
