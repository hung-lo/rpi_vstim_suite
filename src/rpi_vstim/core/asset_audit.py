"""Read-only identity checks for the frozen Stringer natural-image corpus."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

IMAGE_COUNT = 2800
IMAGE_RE = re.compile(r"^natimg_center_(\d{4})\.png$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class AssetAuditError(ValueError):
    """Raised when corpus or session image identity cannot be verified."""


def verify_corpus(root: Path | str) -> dict[str, object]:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise AssetAuditError("asset root is not a directory")
    expected_names = tuple(f"natimg_center_{index:04d}.png" for index in range(IMAGE_COUNT))
    actual_names = tuple(sorted(path.name for path in root.glob("*.png")))
    if actual_names != expected_names:
        raise AssetAuditError("PNG filenames are not exactly natimg_center_0000..2799.png")
    allowed = set(expected_names) | {"README.md", "LICENSE.md", "MANIFEST.sha256"}
    if {path.name for path in root.iterdir()} != allowed:
        raise AssetAuditError("asset directory contains unexpected or missing files")

    manifest = root / "MANIFEST.sha256"
    expected_manifest = []
    for index, name in enumerate(expected_names):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise AssetAuditError(f"invalid corpus file: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_manifest.append(f"{digest}  {name}\n")
        header = path.read_bytes()[:33]
        if len(header) != 33 or header[:8] != _PNG_SIGNATURE:
            raise AssetAuditError(f"invalid PNG header: {name}")
        length = struct.unpack(">I", header[8:12])[0]
        chunk_type = header[12:16]
        dimensions = struct.unpack(">II", header[16:24])
        bit_depth, color_type = header[24:26]
        expected_crc = struct.unpack(">I", header[29:33])[0]
        actual_crc = zlib.crc32(header[12:29]) & 0xFFFFFFFF
        if (length, chunk_type, bit_depth, color_type, expected_crc) != (
            13, b"IHDR", 8, 0, actual_crc
        ):
            raise AssetAuditError(f"invalid 8-bit grayscale PNG IHDR: {name}")
        if dimensions != (90, 68):
            raise AssetAuditError(f"wrong PNG dimensions for {name}: {dimensions}")
        match = IMAGE_RE.fullmatch(name)
        if match is None or int(match.group(1)) != index:
            raise AssetAuditError(f"invalid image ID ordering at {name}")

    manifest_text = manifest.read_text(encoding="ascii")
    expected_text = "".join(expected_manifest)
    if manifest_text != expected_text:
        raise AssetAuditError("MANIFEST.sha256 does not match the corpus files")
    return {
        "asset_root": str(root),
        "images": IMAGE_COUNT,
        "first": expected_names[0],
        "last": expected_names[-1],
        "dimensions": [90, 68],
        "mode": "L",
        "manifest_sha256": hashlib.sha256(expected_text.encode("ascii")).hexdigest(),
    }


def compare_legacy_corpus(current_root: Path | str, legacy_root: Path | str) -> dict[str, object]:
    current_root, legacy_root = Path(current_root).resolve(), Path(legacy_root).resolve()
    if not legacy_root.is_dir():
        raise AssetAuditError("legacy image directory is unavailable")
    current = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
               for path in current_root.glob("*.png") if path.is_file()}
    legacy = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in legacy_root.glob("*.png") if path.is_file()}
    missing = sorted(set(current) - set(legacy))
    extra = sorted(set(legacy) - set(current))
    mismatched = sorted(name for name in current.keys() & legacy.keys()
                        if current[name] != legacy[name])
    return {
        "legacy_root": str(legacy_root),
        "matches": not (missing or extra or mismatched),
        "current_pngs": len(current),
        "legacy_pngs": len(legacy),
        "missing": missing,
        "extra": extra,
        "sha256_mismatches": mismatched,
    }


def verify_session_selection(session_root: Path | str, asset_root: Path | str) -> dict[str, object]:
    session_root, asset_root = Path(session_root).resolve(), Path(asset_root).resolve()
    try:
        plan = json.loads((session_root / "plan.json").read_text(encoding="utf-8"))
        table = json.loads((session_root / "selected_image_table.json").read_text(encoding="utf-8"))
        manifest = json.loads((session_root / "asset_manifest.json").read_text(encoding="utf-8"))
        config = json.loads((session_root / "resolved_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssetAuditError("session image identity artifacts are missing or invalid") from exc

    if not all(isinstance(value, dict) for value in (plan, table, manifest, config)):
        raise AssetAuditError("session image identity artifacts must be JSON objects")
    metadata = plan.get("metadata")
    selected = metadata.get("selected_images") if isinstance(metadata, dict) else None
    rows = table.get("images")
    manifest_entries = manifest.get("entries")
    if not isinstance(manifest_entries, list):
        raise AssetAuditError("asset_manifest.json has no entry list")
    entries = {row.get("relative_path"): row.get("sha256")
               for row in manifest_entries if isinstance(row, dict)}
    if not isinstance(selected, list) or not isinstance(rows, list) or len(selected) != len(rows):
        raise AssetAuditError("plan and selected image table have different image counts")
    verified = []
    for index, (expected_name, row) in enumerate(zip(selected, rows), 1):
        if (not isinstance(expected_name, str) or not isinstance(row, dict)
                or row.get("index") != index or row.get("image") != expected_name
                or not IMAGE_RE.fullmatch(expected_name)):
            raise AssetAuditError(f"selected image table does not match plan at sequence {index}")
        path = asset_root / expected_name
        try:
            if path.resolve(strict=True).parent != asset_root or path.is_symlink():
                raise AssetAuditError(f"session image path escapes corpus at sequence {index}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise AssetAuditError(f"session image is missing at sequence {index}") from exc
        if row.get("sha256") != digest or entries.get(expected_name) != digest:
            raise AssetAuditError(f"session image hash does not match corpus at sequence {index}")
        verified.append({"sequence_index": index, "image": expected_name, "sha256": digest})
    paths = config.get("paths")
    resolved_root = paths.get("asset_root") if isinstance(paths, dict) else None
    final_status_path = session_root / "final_status.json"
    final_status = None
    if final_status_path.is_file():
        try:
            final_status = json.loads(final_status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AssetAuditError("session final_status.json is invalid") from exc
        if not isinstance(final_status, dict):
            raise AssetAuditError("session final_status.json is invalid")
        if final_status.get("session_id") not in (None, session_root.name):
            raise AssetAuditError("final_status.json belongs to a different session")

    events_path = session_root / "events.jsonl"
    image_onsets = []
    if (final_status and final_status.get("status") == "COMPLETE"
            and not events_path.is_file()):
        raise AssetAuditError("complete session events.jsonl is missing")
    if events_path.is_file():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise AssetAuditError("session events.jsonl contains an invalid record")
                is_image = event.get("event") == "IMAGE_ONSET" or (
                    event.get("event") == "SIMULATED_STIMULUS_PLAN_EVENT"
                    and event.get("kind") == "image"
                )
                if is_image:
                    image_onsets.append(event)
        except (OSError, ValueError) as exc:
            raise AssetAuditError("session events.jsonl is invalid") from exc
        for index, (event, selected_image) in enumerate(zip(image_onsets, verified), 1):
            if (event.get("session_id") != session_root.name
                    or event.get("filename") != selected_image["image"]
                    or event.get("image_sha256") != selected_image["sha256"]
                    or event.get("trial_id") != str(index)
                    or event.get("sequence_id") != f"image-{index}"
                    or event.get("image_index") not in (None, index)):
                raise AssetAuditError(f"image onset identity does not match plan at sequence {index}")
        if len(image_onsets) > len(verified):
            raise AssetAuditError("events.jsonl has more image onsets than the selected plan")
        if final_status and final_status.get("status") == "COMPLETE" and len(image_onsets) != len(verified):
            raise AssetAuditError("complete session image onsets do not cover the selected plan")
    return {
        "session_id": session_root.name,
        "resolved_asset_root": resolved_root,
        "asset_root_matches": str(resolved_root) == str(asset_root),
        "selected_images": verified,
        "final_status": final_status.get("status") if final_status else None,
        "image_onset_events_checked": len(image_onsets),
        "event_log_checked": events_path.is_file(),
    }
