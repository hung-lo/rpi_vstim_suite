"""Stable digest of the behavior-bearing parts of a session."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


_VOLATILE_KEYS = {
    "created_utc_ns",
    "updated_utc_ns",
    "start_utc_ns",
    "stop_utc_ns",
    "start_monotonic_ns",
    "stop_monotonic_ns",
    "first_page_flip_callback_monotonic_ns",
    "last_page_flip_callback_monotonic_ns",
    "first_page_flip_callback_realtime_ns",
    "timestamp_utc_ns",
    "timestamp_monotonic_ns",
}
_PATH_KEYS = {"session_id", "session_root", "output_path", "diagnostic_log_path"}
_ASSET_VOLATILE_KEYS = {"mtime_ns", "inode"}


def _stable(value: Any, *, artifact: str = "") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in sorted(value.items()):
            if key in _VOLATILE_KEYS or key in _PATH_KEYS:
                continue
            if artifact == "asset_manifest" and key in _ASSET_VOLATILE_KEYS:
                continue
            result[key] = _stable(item, artifact=artifact)
        return result
    if isinstance(value, list):
        return [_stable(item, artifact=artifact) for item in value]
    return value


def _read_json(root: Path, name: str, artifact: str) -> Any:
    path = root / name
    if not path.is_file():
        return None
    value = _stable(json.loads(path.read_text(encoding="utf-8")), artifact=artifact)
    if artifact == "asset_manifest" and isinstance(value, dict):
        stable_value = {key: item for key, item in value.items() if key != "manifest_hash"}
        value["manifest_hash"] = hashlib.sha256(
            json.dumps(stable_value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return value


def canonical_session(root: Path | str) -> dict[str, Any]:
    """Return the timestamp/path-free session representation used for replay."""
    session_root = Path(root)
    events: list[dict[str, str]] = []
    events_path = session_root / "events.csv"
    if events_path.is_file():
        with events_path.open(encoding="utf-8", newline="") as handle:
            events = [
                {key: row.get(key, "") for key in ("event", "lifecycle", "sequence_id", "detail")}
                for row in csv.DictReader(handle)
            ]
    display: list[Any] = []
    display_path = session_root / "display_results.jsonl"
    if display_path.is_file():
        display = [
            _stable(json.loads(line), artifact="display_result")
            for line in display_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    final_status = _read_json(session_root, "final_status.json", "session_manifest")
    artifacts = {
        name: _read_json(session_root, name, artifact)
        for name, artifact in (
            ("session_manifest.json", "session_manifest"),
            ("resolved_config.json", "config"),
            ("plan.json", "plan"),
            ("asset_manifest.json", "asset_manifest"),
            ("display_results.json", "display_summary"),
            ("resource_summary.json", "resource_summary"),
        )
    }
    return {
        "schema_versions": {
            name: value.get("schema_version") if isinstance(value, dict) else None
            for name, value in artifacts.items()
        },
        "plan": artifacts["plan.json"],
        "asset_manifest": artifacts["asset_manifest.json"],
        "display": display,
        "events": events,
        "final": {
            key: final_status.get(key)
            for key in ("status", "lifecycle", "phase", "degraded", "error", "incomplete", "outputs_finalized")
            if isinstance(final_status, dict) and key in final_status
        },
    }


def session_digest(root: Path | str) -> str:
    payload = json.dumps(canonical_session(root), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
