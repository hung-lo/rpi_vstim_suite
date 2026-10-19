import hashlib
import json
import shutil

import pytest
from PIL import Image

from rpi_vstim.core.asset_audit import (
    AssetAuditError,
    compare_legacy_corpus,
    verify_corpus,
    verify_session_selection,
)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("stringer-corpus")
    (root / "README.md").write_text("fixture\n")
    (root / "LICENSE.md").write_text("fixture\n")
    content = root / "source.png"
    Image.new("L", (90, 68), 127).save(content)
    png = content.read_bytes()
    content.unlink()
    lines = []
    for index in range(2800):
        name = f"natimg_center_{index:04d}.png"
        (root / name).write_bytes(png)
        lines.append(f"{hashlib.sha256(png).hexdigest()}  {name}\n")
    (root / "MANIFEST.sha256").write_text("".join(lines))
    return root


def _copy_corpus(corpus, tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    return root


def test_complete_corpus_identity(corpus):
    result = verify_corpus(corpus)
    assert result["images"] == 2800
    assert result["first"] == "natimg_center_0000.png"
    assert result["last"] == "natimg_center_2799.png"
    assert result["dimensions"] == [90, 68]


def test_missing_png_is_rejected(corpus, tmp_path):
    root = _copy_corpus(corpus, tmp_path)
    (root / "natimg_center_0001.png").unlink()
    with pytest.raises(AssetAuditError, match="filenames"):
        verify_corpus(root)


def test_incorrect_sha256_is_rejected(corpus, tmp_path):
    root = _copy_corpus(corpus, tmp_path)
    path = root / "natimg_center_0001.png"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(AssetAuditError, match="MANIFEST"):
        verify_corpus(root)


def test_wrong_dimensions_are_rejected(corpus, tmp_path):
    root = _copy_corpus(corpus, tmp_path)
    Image.new("L", (90, 67), 127).save(root / "natimg_center_0001.png")
    with pytest.raises(AssetAuditError, match="dimensions"):
        verify_corpus(root)


def test_invalid_filename_is_rejected(corpus, tmp_path):
    root = _copy_corpus(corpus, tmp_path)
    (root / "natimg_center_0000.png").rename(root / "natimg_center_2800.png")
    with pytest.raises(AssetAuditError, match="filenames"):
        verify_corpus(root)


def _session(root, corpus, *, image="natimg_center_0001.png", plan_image=None, index=1):
    root.mkdir()
    plan_image = image if plan_image is None else plan_image
    image_path = corpus / image
    digest = hashlib.sha256(image_path.read_bytes() if image_path.is_file() else b"").hexdigest()
    (root / "plan.json").write_text(json.dumps({"metadata": {"selected_images": [plan_image]}}))
    (root / "selected_image_table.json").write_text(json.dumps({
        "images": [{"index": index, "image": image, "sha256": digest}],
    }))
    (root / "asset_manifest.json").write_text(json.dumps({
        "entries": [{"relative_path": image, "sha256": digest}],
    }))
    (root / "resolved_config.json").write_text(json.dumps({
        "paths": {"asset_root": str(corpus)},
    }))
    (root / "events.jsonl").write_text(json.dumps({
        "event": "IMAGE_ONSET", "session_id": root.name, "trial_id": "1",
        "sequence_id": "image-1",
        "image_index": 1, "filename": image, "image_sha256": digest,
    }) + "\n")
    (root / "final_status.json").write_text(json.dumps({
        "session_id": root.name, "status": "COMPLETE",
    }))


def test_session_selection_reconstructs_exact_image_and_hash(corpus, tmp_path):
    root = tmp_path / "session-1"
    _session(root, corpus)
    result = verify_session_selection(root, corpus)
    assert result["selected_images"][0]["sequence_index"] == 1
    assert result["selected_images"][0]["image"] == "natimg_center_0001.png"
    assert result["asset_root_matches"] is True
    assert result["image_onset_events_checked"] == 1
    assert result["event_log_checked"] is True
    assert result["final_status"] == "COMPLETE"


def test_complete_session_onsets_must_match_selected_plan(corpus, tmp_path):
    root = tmp_path / "session-1"
    _session(root, corpus)
    event_path = root / "events.jsonl"
    event = json.loads(event_path.read_text())
    event["trial_id"] = "2"
    event_path.write_text(json.dumps(event) + "\n")
    with pytest.raises(AssetAuditError, match="sequence 1"):
        verify_session_selection(root, corpus)


def test_malformed_session_manifest_is_rejected(corpus, tmp_path):
    root = tmp_path / "session-1"
    _session(root, corpus)
    (root / "asset_manifest.json").write_text(json.dumps({"entries": None}))
    with pytest.raises(AssetAuditError, match="entry list"):
        verify_session_selection(root, corpus)


@pytest.mark.parametrize(
    ("image", "plan_image", "index", "match"),
    [
        ("natimg_center_0001.png", None, 2, "sequence 1"),
        ("natimg_center_0001.png", "natimg_center_0002.png", 1, "plan"),
        ("../outside.png", None, 1, "plan"),
    ],
)
def test_session_wrong_index_selection_and_traversal_are_rejected(
    corpus, tmp_path, image, plan_image, index, match
):
    root = tmp_path / "session-1"
    _session(root, corpus, image=image, plan_image=plan_image, index=index)
    with pytest.raises(AssetAuditError, match=match):
        verify_session_selection(root, corpus)


def test_optional_legacy_corpus_comparison(corpus, tmp_path):
    legacy = tmp_path / "legacy"
    shutil.copytree(corpus, legacy)
    assert compare_legacy_corpus(corpus, legacy)["matches"] is True
    (legacy / "natimg_center_0001.png").write_bytes(b"different")
    result = compare_legacy_corpus(corpus, legacy)
    assert result["matches"] is False
    assert result["sha256_mismatches"] == ["natimg_center_0001.png"]
