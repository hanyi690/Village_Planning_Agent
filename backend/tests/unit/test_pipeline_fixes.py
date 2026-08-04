"""P0/P1 修复单测：slope 因子 / 面积回填 / DLBM 别名匹配 / shutdown 超时。"""

import asyncio
import math
import types

import numpy as np
import pytest
from shapely.geometry import Polygon


# ── P1-7: slope 因子（np.gradient 自实现 + RasterLayerGroup 字段取值）──

def _make_dem_tif(path, width=30, height=30):
    import rasterio
    from rasterio.transform import from_origin

    # EPSG:4326 度网格 ~30m；左半 0m 右半 100m → 陡坡
    deg = 0.0002778
    elev = np.zeros((height, width), dtype="float64")
    elev[:, width // 2:] = 100.0
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1,
        dtype="float64", crs="EPSG:4326",
        transform=from_origin(116.0, 25.0, deg, deg),
    ) as dst:
        dst.write(elev, 1)


def _fake_bundle(dem_path, n_parcels=2):
    # 地块质心落在 DEM 陡坡侧（x 116.004~116.006），范围在 30x30 DEM 内
    polys = [
        types.SimpleNamespace(
            bsm=f"B{i}",
            geometry=Polygon([(116.004 + i * 0.001, 24.993), (116.006 + i * 0.001, 24.993),
                              (116.006 + i * 0.001, 24.995), (116.004 + i * 0.001, 24.995)]),
        )
        for i in range(n_parcels)
    ]
    return types.SimpleNamespace(
        rasters=types.SimpleNamespace(
            dem=types.SimpleNamespace(path=str(dem_path))
        ),
        polygons={"landuse_current": polys},
    )


def test_load_dem_slope(tmp_path):
    from app.agent.execute.vocab_context import _load_dem_slope

    dem = tmp_path / "dem.tif"
    _make_dem_tif(dem)
    bundle = _fake_bundle(dem)
    res = _load_dem_slope(bundle)
    assert res is not None
    assert set(res) == {"B0", "B1"}
    for v in res.values():
        assert 0.0 <= v <= 90.0


def test_load_dem_slope_missing_dem(tmp_path):
    from app.agent.execute.vocab_context import _load_dem_slope

    bundle = types.SimpleNamespace(
        rasters=types.SimpleNamespace(dem=None), polygons={"landuse_current": []}
    )
    assert _load_dem_slope(bundle) is None


# ── P1-6: 面积回填（命中不足 → 候选池补足至 ±30%）──

def _parcel(bsm, area_ha):
    return {"bsm": bsm, "area_ha": area_ha}


def test_supplement_by_area_fills_gap():
    from app.tools.gis._generation.custom_zone_generator import _supplement_by_area

    selected = [_parcel("B1", 1.0)]
    pool = [_parcel("B2", 2.0), _parcel("B3", 3.0), _parcel("B4", 4.0)]
    filled, supplemented = _supplement_by_area(selected, 10.0, pool)
    assert supplemented is True
    total = sum(p["area_ha"] for p in filled)
    assert total >= 7.0  # 70% of 10ha
    # 按面积降序补足到 70%：B4(4)+B3(3)=7 即停，B2 无需
    assert {p["bsm"] for p in filled} == {"B1", "B4", "B3"}


def test_supplement_by_area_no_gap():
    from app.tools.gis._generation.custom_zone_generator import _supplement_by_area

    selected = [_parcel("B1", 8.0), _parcel("B2", 3.0)]
    filled, supplemented = _supplement_by_area(selected, 10.0, [])
    assert supplemented is False
    assert len(filled) == 2


def test_truncate_by_area_caps_over_target():
    from app.tools.gis._generation.custom_zone_generator import _truncate_by_area

    parcels = [_parcel("B1", 6.0), _parcel("B2", 5.0), _parcel("B3", 2.0)]
    chosen = _truncate_by_area(parcels, 10.0)
    assert len(chosen) == 2  # 6+5 >= 10


# ── P1-5: DLBM 分区别名匹配 ──

def test_match_parcel_indices_alias():
    from app.tools.gis._generation.zone_generator import ZoneGenerator

    gen = ZoneGenerator()
    parcel_zones = {
        "农业用地": [0, 1, 2],
        "生态绿地": [3, 4],
        "居住用地": [5],
        "水域": [6],
    }
    for name, expected in (
        ("一般农业区", [0, 1, 2]),
        ("基本农田保护区", [0, 1, 2]),
        ("生态保护区", [3, 4]),
        ("林业发展区", [3, 4]),
        ("村庄建设区", [5]),
        ("水域保护区", [6]),
    ):
        assert gen._match_parcel_indices(name, parcel_zones, None) == expected


def test_match_parcel_indices_substring_and_dlbm():
    from app.tools.gis._generation.zone_generator import ZoneGenerator
    from app.modules.schema.contracts.parse_contracts import ZoneTarget

    gen = ZoneGenerator()
    parcel_zones = {"生态绿地": [3, 4]}
    # 子串命中："生态区" 是 "生态绿地" 子串的反向（标准名 in 名）
    assert gen._match_parcel_indices("生态区", parcel_zones, None) == [3, 4]
    # dlbm 映射兜底
    zt = ZoneTarget(land_use="未知区", dlbm="0401", area_ratio=0.1)
    assert gen._match_parcel_indices("未知区", parcel_zones, zt) == [3, 4]
    # 空名不猜测
    assert gen._match_parcel_indices("", parcel_zones, None) == []


# ── P0-2: shutdown_database 超时兜底 ──

def test_shutdown_database_timeout_bounded():
    import app.database.engine as eng

    async def _hung_conn_close():
        await asyncio.sleep(60)

    class _HungCkpt:
        conn = None

    _HungCkpt.conn = types.SimpleNamespace(close=_hung_conn_close, stop=lambda: None)

    old_ckpt, old_init, old_engine = (
        eng._checkpointer, eng._checkpointer_initialized, eng.async_engine,
    )
    eng._checkpointer = _HungCkpt()
    eng._checkpointer_initialized = True
    eng.async_engine = None
    try:
        started = asyncio.get_event_loop().time() if False else None
        import time
        t0 = time.monotonic()
        asyncio.run(eng.shutdown_database())
        elapsed = time.monotonic() - t0
        assert elapsed < 20  # 5s 超时 + 缓冲，绝不等 60s
    finally:
        eng._checkpointer, eng._checkpointer_initialized, eng.async_engine = (
            old_ckpt, old_init, old_engine,
        )
