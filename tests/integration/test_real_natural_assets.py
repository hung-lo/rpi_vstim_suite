from pathlib import Path

import pytest

from rpi_vstim.core.assets import AssetResolver
from rpi_vstim.core.config import load_config
from rpi_vstim.core.runtime import build_simulation_plan
from rpi_vstim.protocols.natural_images import discover_images

pytest.importorskip("PIL.Image")


def test_production_config_discovers_real_corpus_and_decodes_one_image():
    config = load_config(Path("config/protocols/natural_images.example.toml"))
    names = discover_images(config.paths.asset_root)
    assert len(names) == 2800
    plan = build_simulation_plan(config, protocol_name="natural-images", seed=0)
    assert all(name in names for name in plan.metadata["selected_images"])

    metadata = AssetResolver(config.paths.asset_root).metadata(names[0])
    assert (metadata.width_px, metadata.height_px, metadata.mode) == (90, 68, "L")
