from __future__ import annotations

import json
from dataclasses import replace

import pytest

from rpi_vstim.core.config import Config
from rpi_vstim.core.session import new_session
from rpi_vstim.core.storage import (
    DEFAULT_MIN_FREE_BYTES,
    StoragePreflightError,
    prepare_session_output_root,
)


def _production_root(monkeypatch, tmp_path):
    from rpi_vstim.core import storage

    mount = tmp_path / "behavbox_ssd"
    mount.mkdir()
    monkeypatch.setattr(storage, "PRODUCTION_STORAGE_MOUNT", mount)
    monkeypatch.setattr(storage, "PRODUCTION_SESSION_ROOT", mount / "sessions")
    monkeypatch.setattr(storage, "PRODUCTION_STORAGE_SOURCE", "/dev/nvme0n1p1")
    monkeypatch.setattr(storage, "PRODUCTION_STORAGE_UUID", "expected-uuid")
    monkeypatch.setattr(storage.os.path, "ismount", lambda path: path == mount)
    monkeypatch.setattr(
        storage,
        "_mount_info",
        lambda _path: {"source": "/dev/nvme0n1p1", "fstype": "ext4", "uuid": "expected-uuid"},
    )
    return mount / "sessions"


def test_explicit_development_root_remains_usable(tmp_path):
    root = tmp_path / "local-output"
    snapshot = prepare_session_output_root(root)
    assert root.is_dir()
    assert not snapshot.production_storage


def test_production_root_requires_a_mountpoint(tmp_path, monkeypatch):
    root = _production_root(monkeypatch, tmp_path)
    from rpi_vstim.core import storage

    monkeypatch.setattr(storage.os.path, "ismount", lambda _path: False)
    with pytest.raises(StoragePreflightError, match="not mounted"):
        prepare_session_output_root(root)


@pytest.mark.parametrize(
    "mount",
    [
        {"source": "/dev/sda1", "fstype": "ext4", "uuid": "expected-uuid"},
        {"source": "/dev/nvme0n1p1", "fstype": "xfs", "uuid": "expected-uuid"},
        {"source": "/dev/nvme0n1p1", "fstype": "ext4", "uuid": "wrong-uuid"},
    ],
)
def test_production_root_rejects_wrong_backing_filesystem(tmp_path, monkeypatch, mount):
    root = _production_root(monkeypatch, tmp_path)
    from rpi_vstim.core import storage

    monkeypatch.setattr(storage, "_mount_info", lambda _path: mount)
    with pytest.raises(StoragePreflightError, match="expected filesystem"):
        prepare_session_output_root(root)


def test_production_root_rejects_unwritable_root(tmp_path, monkeypatch):
    root = _production_root(monkeypatch, tmp_path)
    from rpi_vstim.core import storage

    monkeypatch.setattr(storage, "_writable", lambda _path: False)
    with pytest.raises(StoragePreflightError, match="not writable"):
        prepare_session_output_root(root)


def test_production_root_rejects_low_free_space(tmp_path, monkeypatch):
    root = _production_root(monkeypatch, tmp_path)
    from rpi_vstim.core import storage

    real_snapshot = storage.storage_snapshot

    def low_space(path):
        value = real_snapshot(path)
        return replace(value, free_bytes=DEFAULT_MIN_FREE_BYTES - 1)

    monkeypatch.setattr(storage, "storage_snapshot", low_space)
    with pytest.raises(StoragePreflightError, match="need at least"):
        prepare_session_output_root(root)


def test_session_root_is_unique_and_storage_is_recorded(tmp_path):
    config = replace(Config(), paths=replace(Config().paths, output_root=tmp_path / "sessions"))
    first = new_session(config, session_id="unique")
    first.write_initial_outputs()
    with pytest.raises(FileExistsError):
        new_session(config, session_id="unique").write_initial_outputs()
    first.update_status("COMPLETE", lifecycle="COMPLETE")
    first.close()
    provenance = json.loads((tmp_path / "sessions" / "unique" / "provenance.json").read_text())
    assert provenance["storage_start"]["output_root"] == str(tmp_path / "sessions")
    assert provenance["storage_end"]["free_bytes"] > 0
