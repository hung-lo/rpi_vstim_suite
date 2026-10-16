"""Small version checks for durable JSON artifacts."""

from __future__ import annotations

from typing import Any


SUPPORTED_SCHEMA_VERSIONS = {
    "session_manifest": 2,
    "provenance": 1,
    "config": 1,
    "plan": 1,
    "preflight": 1,
    "cache_manifest": 1,
    "asset_manifest": 1,
    "display_result": 1,
    "display_summary": 1,
    "resource_summary": 1,
    "camera_manifest": 1,
}


def versioned(value: Any, artifact: str) -> Any:
    if not isinstance(value, dict):
        return value
    return {**value, "schema_version": SUPPORTED_SCHEMA_VERSIONS[artifact]}


def validate(value: Any, artifact: str) -> str | None:
    if not isinstance(value, dict):
        return f"{artifact} must be a JSON object"
    expected = SUPPORTED_SCHEMA_VERSIONS[artifact]
    actual = value.get("schema_version")
    if actual != expected:
        return f"{artifact} schema_version {actual!r} is unsupported; expected {expected}"
    return None
