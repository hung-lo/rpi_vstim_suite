import os
import shutil
from collections import namedtuple
from pathlib import Path

import pytest

from rpi_vstim.core.storage import (
    StorageMonitor,
    finalize_storage_session,
    open_storage_session,
    preflight_storage,
)
import rpi_vstim.core.storage as storage


def test_storage_preflight_can_use_an_explicit_test_directory(tmp_path):
    result = preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        minimum_free_bytes=1,
        estimated_required_bytes=1,
        expected_device="test-device",
        identity_reader=lambda _path: "test-device",
    )
    assert result.passed
    assert result.status == "ready"


def test_storage_preflight_fails_closed_for_unmounted_production_root(tmp_path):
    result = preflight_storage(tmp_path, allow_test_path=True)
    assert not result.passed
    assert result.status == "failed:mounted"


def test_storage_preflight_rejects_insufficient_estimated_space(tmp_path):
    free = shutil.disk_usage(tmp_path).free
    result = preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        estimated_required_bytes=free + 1,
    )
    assert not result.passed
    assert result.status == "failed:estimated_required_bytes"


def test_storage_preflight_rejects_identity_mismatch(tmp_path):
    result = preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        expected_device="ssd-uuid",
        identity_reader=lambda _path: "sd-card-uuid",
    )
    assert not result.passed
    assert result.status == "failed:expected_device"


@pytest.mark.parametrize("unsafe_root", ["/tmp", "/var/tmp"])
def test_storage_preflight_rejects_children_of_unsafe_roots(unsafe_root):
    result = preflight_storage(unsafe_root + "/rpi-vstim-session")
    assert not result.passed
    assert result.status == "failed:safe_production_root"


def test_storage_preflight_write_probe_is_bounded_and_serializable(tmp_path):
    result = preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        write_probe=True,
    )
    assert result.passed
    assert result.as_dict()["path"] == str(tmp_path.resolve())


def test_storage_session_keeps_incomplete_marker_until_required_outputs_exist(tmp_path):
    preflight = preflight_storage(tmp_path, require_mount=False, allow_test_path=True)
    session = open_storage_session(preflight, "session-1")
    assert session.marker_path.exists()
    incomplete = finalize_storage_session(
        session,
        required_files=("plan.json",),
        success=True,
    )
    assert not incomplete.complete
    assert incomplete.marker_retained
    (session.session_root / "plan.json").write_text("{}\n")
    complete = finalize_storage_session(
        session,
        required_files=("plan.json",),
        success=True,
    )
    assert complete.complete
    assert not session.marker_path.exists()
    assert StorageMonitor(tmp_path, minimum_free_bytes=1).check()["passed"]


def test_storage_faults_fail_closed_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.os, "access", lambda *_args: False)
    assert preflight_storage(tmp_path, require_mount=False, allow_test_path=True).status == "failed:writable"

    monkeypatch.setattr(storage.os, "access", lambda *_args: True)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda _path: usage(100, 99, 1))
    assert preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        estimated_required_bytes=2,
    ).status == "failed:estimated_required_bytes"

    monkeypatch.setattr(storage, "_write_probe", lambda _root: (False, "fsync denied"))
    assert not preflight_storage(
        tmp_path,
        require_mount=False,
        allow_test_path=True,
        write_probe=True,
    ).passed


def test_storage_session_collision_and_path_replacement_are_explicit(tmp_path):
    preflight = preflight_storage(tmp_path, require_mount=False, allow_test_path=True)
    (tmp_path / "collision").mkdir()
    with pytest.raises(FileExistsError):
        open_storage_session(preflight, "collision")

    original = tmp_path / "original"
    original.mkdir()
    checked = preflight_storage(original, require_mount=False, allow_test_path=True)
    moved = tmp_path / "moved"
    original.rename(moved)
    os.symlink(tmp_path / "outside", original)
    with pytest.raises(FileNotFoundError):
        open_storage_session(checked, "session")
    Path(original).unlink()
