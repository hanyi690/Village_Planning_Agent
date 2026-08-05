from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from tests.fixtures.road.demo_terrain import _write_geotiff


def test_qgis_geotiff_declares_wgs84_and_nodata(tmp_path: Path) -> None:
    path = tmp_path / "terrain_wgs84.tif"
    values = np.array([[100.0, -9999.0], [120.0, 140.0]], dtype=np.float32)
    _write_geotiff(
        path,
        values,
        116.0,
        25.0,
        1.0 / 3600.0,
        1.0 / 3600.0,
        epsg=4326,
    )

    image = Image.open(path)
    keys = tuple(image.tag_v2[34735])
    assert image.tag_v2[42113] == "-9999.0"
    assert keys[-4:] == (2048, 0, 1, 4326)
    assert image.tag_v2[33550] == (1.0 / 3600.0, 1.0 / 3600.0, 0.0)
