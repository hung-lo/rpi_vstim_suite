import shutil

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
    result = preflight_storage(tmp_path)
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
