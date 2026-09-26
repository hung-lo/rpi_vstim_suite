from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from .config import Config
from .event_log import EventLogger
from .provenance import collect_provenance, resolve_source_commit
from .timestamps import monotonic_ns, utc_ns

_SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_jsonable(value), handle, indent=2, sort_keys=True)
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
        self._manifest: dict[str, Any] = {}
        self._events: EventLogger | None = None
        self._display_stream: TextIO | None = None
        self._display_summary = {
            "schema_version": 1,
            "record_count": 0,
            "requested_frame_count": 0,
            "completed_frame_count": 0,
            "incomplete": True,
        }

    def write_initial_outputs(self) -> None:
        self.context.session_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.context.session_root / "resolved_config.json", self.context.resolved_config)
        atomic_write_json(self.context.session_root / "provenance.json", self.context.host_provenance)
        self._manifest = {
            "session_id": self.context.session_id,
            "protocol": self.context.protocol_name,
            "protocol_version": self.context.protocol_version,
            "created_utc_ns": self.context.created_utc_ns,
            "random_seeds": self.context.random_seeds,
            "source_commit": self.context.source_commit,
            "status": "CREATED",
            "lifecycle": "CREATED",
            "phase": "00",
            "degraded": [],
        }
        self._write_manifest()
        self._events = EventLogger(self.context.session_root / "events.csv")
        self._events.open(["event", "lifecycle", "sequence_id", "timestamp_utc_ns", "detail"])
        self._display_stream = (self.context.session_root / "display_results.jsonl").open(
            "w", encoding="utf-8"
        )
        atomic_write_json(
            self.context.session_root / "display_results.json",
            self._display_summary,
        )
        self.record_event("SESSION_CREATED", lifecycle="CREATED")

    def _write_manifest(self) -> None:
        atomic_write_json(self.context.session_root / "session_manifest.json", self._manifest)

    def write_plan(self, plan: Any) -> None:
        value = plan.as_dict() if hasattr(plan, "as_dict") else plan
        atomic_write_json(self.context.session_root / "plan.json", value)
        if isinstance(value, dict) and value.get("metadata", {}).get("selected_images"):
            atomic_write_json(
                self.context.session_root / "selected_image_table.json",
                {
                    "images": [
                        {"index": index, "image": image}
                        for index, image in enumerate(value["metadata"]["selected_images"], 1)
                    ]
                },
            )

    def write_preflight_report(self, report: Any) -> None:
        value = asdict(report) if is_dataclass(report) else report
        atomic_write_json(self.context.session_root / "preflight_report.json", value)

    def write_cache_manifest(self, value: Any) -> None:
        value = asdict(value) if is_dataclass(value) else value
        atomic_write_json(self.context.session_root / "cache_manifest.json", value)

    def write_asset_manifest(self, value: Any) -> None:
        value = value.as_dict() if hasattr(value, "as_dict") else value
        atomic_write_json(self.context.session_root / "asset_manifest.json", value)

    def write_display_result(self, result: Any) -> None:
        if self._display_stream is None:
            raise RuntimeError("session outputs are not initialized")
        value = asdict(result) if is_dataclass(result) else result
        self._display_stream.write(json.dumps(_jsonable(value), sort_keys=True) + "\n")
        self._display_stream.flush()
        self._display_summary["record_count"] += 1
        if isinstance(value, dict):
            self._display_summary["requested_frame_count"] += int(
                value.get("requested_frame_count", 0)
            )
            self._display_summary["completed_frame_count"] += int(
                value.get("completed_frame_count", 0)
            )
        atomic_write_json(
            self.context.session_root / "display_results.json",
            self._display_summary,
        )

    def write_resource_summary(self, value: Any) -> None:
        value = asdict(value) if is_dataclass(value) else value
        atomic_write_json(self.context.session_root / "resource_summary.json", value)

    def record_event(
        self,
        event: str,
        *,
        lifecycle: str = "",
        sequence_id: str = "",
        detail: str = "",
    ) -> None:
        if self._events is None:
            raise RuntimeError("session outputs are not initialized")
        self._events.write(
            {
                "event": event,
                "lifecycle": lifecycle,
                "sequence_id": sequence_id,
                "timestamp_utc_ns": utc_ns(),
                "detail": detail,
            }
        )

    def update_status(
        self,
        status: str,
        *,
        lifecycle: str | None = None,
        error: str | None = None,
        degraded: list[str] | None = None,
        cleanup_errors: list[str] | None = None,
    ) -> None:
        if not self._manifest:
            raise RuntimeError("session outputs are not initialized")
        self._manifest["status"] = status
        if lifecycle is not None:
            self._manifest["lifecycle"] = lifecycle
        if error is not None:
            self._manifest["error"] = error
        if degraded is not None:
            self._manifest["degraded"] = sorted(set(degraded))
        if cleanup_errors is not None:
            self._manifest["cleanup_errors"] = list(cleanup_errors)
        self._manifest["updated_utc_ns"] = utc_ns()
        self._write_manifest()
        atomic_write_json(self.context.session_root / "final_status.json", self._manifest)

    def close(self) -> None:
        if self._display_stream is not None:
            self._display_stream.flush()
            os.fsync(self._display_stream.fileno())
            self._display_stream.close()
            self._display_stream = None
            self._display_summary["incomplete"] = False
            atomic_write_json(
                self.context.session_root / "display_results.json",
                self._display_summary,
            )
        if self._events is not None:
            self._events.close()
            self._events = None


def new_session(
    config: Config,
    *,
    protocol_name: str | None = None,
    session_id: str = "phase00-simulation",
    seed: int = 0,
) -> SessionOutput:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("session_id contains unsupported characters")
    protocol = protocol_name or config.protocol.name
    source_commit = resolve_source_commit()
    context = SessionContext(
        session_id=session_id,
        protocol_name=protocol,
        protocol_version=config.protocol.version,
        session_root=config.paths.output_root / session_id,
        created_utc_ns=utc_ns(),
        created_monotonic_ns=monotonic_ns(),
        resolved_config=config.as_dict(),
        random_seeds={"protocol": seed},
        source_commit=source_commit,
        host_provenance=collect_provenance(source_commit=source_commit),
    )
    return SessionOutput(context)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
