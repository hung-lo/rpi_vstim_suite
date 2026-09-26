import shutil

import pytest

from rpi_vstim.core.storage import preflight_storage


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
