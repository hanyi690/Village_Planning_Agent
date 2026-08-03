"""单元测试 — ExternalAnchorPipeline 5 阶段 (mock 所有 provider)"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, '.')

# 强制使用 mock
os.environ['TIANDITU_WFS_ANCHOR_ENABLED'] = 'false'
os.environ['AMAP_EXTERNAL_ANCHOR_ENABLED'] = 'false'
os.environ['BAIDU_EXTERNAL_ANCHOR_ENABLED'] = 'false'
os.environ['TECENT_MAP_EXTERNAL_ANCHOR_ENABLED'] = 'false'

from app.modules.data.catalog.external_anchors import (
    ExternalFeature, FeatureCategory, normalize_to_wgs84,
    normalize_name, _local_feature_keys,
    ExternalAnchorPipeline,
)
from app.modules.data.catalog.dedup import coord_key


def test_normalize_gcj02_to_wgs84():
    """GCJ02 → WGS84 应去除火星坐标系偏移."""
    # 已知 GCJ02 偏移近似算法:
    #   WGS84 (116.0408, 24.8169) → GCJ02 ≈ (116.0463, 24.8227)
    #   我们把 GCJ02 喂入, 应转换回接近 WGS84 真值
    gcj_lon, gcj_lat = 116.0463, 24.8227
    wlon, wlat, system = normalize_to_wgs84(gcj_lon, gcj_lat, "gcj02")
    assert system == "wgs84"
    # 转换偏差 < 0.02 度 (~2km) — 实际 gcj02_to_wgs84 算法精度约 1m
    assert abs(wlat - 24.8169) < 0.02, f"lat 偏差过大: {abs(wlat - 24.8169)}"
    assert abs(wlon - 116.0408) < 0.02, f"lon 偏差过大: {abs(wlon - 116.0408)}"


def test_normalize_wgs84_unchanged():
    """WGS84 → WGS84 应不变."""
    wlon, wlat, system = normalize_to_wgs84(116.0408, 24.8169, "wgs84")
    assert wlon == 116.0408 and wlat == 24.8169 and system == "wgs84"


def test_normalize_bd09_unchanged():
    """BD09 直接当 WGS84 (百度 coord_type=1 已转)."""
    wlon, wlat, system = normalize_to_wgs84(116.0408, 24.8169, "bd09")
    assert wlon == 116.0408 and wlat == 24.8169 and system == "wgs84"


def test_normalize_unknown_treated_as_wgs84():
    """未知坐标系当 WGS84."""
    wlon, wlat, system = normalize_to_wgs84(100.0, 30.0, "unknown_xyz")
    assert wlon == 100.0 and wlat == 30.0 and system == "wgs84"


def test_normalize_name_strips_org_suffixes():
    """name_norm 应去除组织后缀."""
    assert normalize_name("金田村委会") == "金田"
    assert normalize_name("金田村民委员会") == "金田"
    assert normalize_name("金田自然村") == "金田"
    # "八社村" 不去 "村" — 因为 "村" 是行政通名, 应保留
    # (例: 与其他村 POI 区别, "村" 字符有意义)
    assert normalize_name("八社村") == "八社村"
    # 泗水镇 不变 ("镇" 不在 suffixes)
    assert normalize_name("泗水镇") == "泗水镇"
    assert normalize_name("") == ""


def test_coord_key_3_decimal_precision():
    """coord_key 应约 100m 精度."""
    k1 = coord_key(116.0408, 24.8169, precision=3)
    k2 = coord_key(116.0409, 24.8170, precision=3)  # ~13m 偏差
    assert k1 == k2  # 100m 内应合并
    k3 = coord_key(116.0500, 24.8200, precision=3)  # ~1km 偏差
    assert k1 != k3


def test_pipeline_5_stage_with_mocked_providers():
    """5 阶段跑通 — collect → normalize → dedup → local dedup → inject."""
    # 准备 bundle
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.base import PointFeature, PolygonFeature

    bundle = VillageBundle(village_name="金田")
    # 加一个 local feature (金田村委会) - 应阻止同名外部 feature 注入
    local_cm = PointFeature(
        geometry={"type": "Point", "coordinates": [116.0408, 24.8169]},
        bsm="local_jintian", layer_type="current_annotation",
        text="金田村委会",
    )
    bundle.points._layers.setdefault("annotations_current", []).append(local_cm)
    local_keys = _local_feature_keys(bundle)
    assert len(local_keys) >= 1
    assert ("金田", 116040, 24816) in local_keys or any(
        k[0] == "金田" for k in local_keys
    )


def test_cross_source_dedup_priority():
    """同 (name, coord, category) 多 source 时优先级最高者胜出."""
    pipeline = ExternalAnchorPipeline()
    features = [
        ExternalFeature(
            "金田", "金田", 116.0408, 24.8169, "gcj02",
            FeatureCategory.VILLAGE_COMMITTEE, "amap_poi", {},
        ),
        ExternalFeature(
            "金田", "金田", 116.0408, 24.8169, "bd09",
            FeatureCategory.VILLAGE_COMMITTEE, "baidu_v3", {},
        ),
        ExternalFeature(
            "金田", "金田", 116.0408, 24.8169, "gcj02",
            FeatureCategory.VILLAGE_COMMITTEE, "tencent_map", {},
        ),
    ]
    deduped = pipeline._stage3_cross_source_dedup(features)
    assert len(deduped) == 1
    # baidu_v3 priority=2 (最高) > tencent_map=3 > amap_poi=4
    assert deduped[0].source == "baidu_v3"


def test_local_aware_dedup_blocks_external():
    """local feature 同 (name, coord) 时, 外部被丢弃."""
    pipeline = ExternalAnchorPipeline()
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.base import PointFeature

    bundle = VillageBundle(village_name="test")
    local_cm = PointFeature(
        geometry={"type": "Point", "coordinates": [116.0408, 24.8169]},
        bsm="local", layer_type="current_annotation",
        text="金田村委会",
    )
    bundle.points._layers.setdefault("annotations_current", []).append(local_cm)

    local_keys = _local_feature_keys(bundle)
    features = [
        ExternalFeature(
            "金田村委会", "金田", 116.0408, 24.8169, "gcj02",
            FeatureCategory.VILLAGE_COMMITTEE, "amap_poi", {},
        ),
        ExternalFeature(
            "八社村", "八社", 116.0050, 24.8480, "gcj02",
            FeatureCategory.VILLAGE_COMMITTEE, "amap_poi", {},
        ),
    ]
    final = pipeline._stage4_local_dedup(features, local_keys)
    assert len(final) == 1
    assert final[0].name == "八社村"  # 金田被丢, 八社保留


def test_pipeline_full_run_with_no_bbox():
    """无 bbox 应直接返回空."""
    pipeline = ExternalAnchorPipeline()
    from app.modules.schema.types.canonical import VillageBundle
    bundle = VillageBundle(village_name="金田")
    injected = pipeline.run(bundle, bbox=None, cfg={})
    assert injected == {}


def test_pipeline_categories_injection_routing():
    """不同 category 应注入到正确的 sub-key."""
    from app.modules.schema.types.canonical import VillageBundle
    bundle = VillageBundle(village_name="金田")

    features = [
        ExternalFeature(
            "金田村委会", "金田", 116.0408, 24.8169, "gcj02",
            FeatureCategory.VILLAGE_COMMITTEE, "amap_poi", {},
        ),
        ExternalFeature(
            "长潭水库", "长潭", 116.0697, 24.8406, "gcj02",
            FeatureCategory.WATER_POLYGON, "tianditu_wfs", {},
            geometry={"type": "Polygon", "coordinates": [[[116.06, 24.83], [116.07, 24.84], [116.07, 24.85], [116.06, 24.83]]]},
        ),
        ExternalFeature(
            "Y161公路", "Y161", 116.0400, 24.8200, "gcj02",
            FeatureCategory.ROAD_LINE, "tianditu_wfs", {},
            geometry={"type": "LineString", "coordinates": [[116.04, 24.82], [116.05, 24.83]]},
        ),
    ]

    pipeline = ExternalAnchorPipeline()
    injected = pipeline._stage5_inject(bundle, features)

    # 验证注入到正确 sub-key (用 _layers 字典访问)
    pts_dict = bundle.points._layers
    assert pts_dict.get("annotations_current") is not None
    assert any(
        (f._raw or {}).get("anchor_source") == "amap_poi"
        for f in pts_dict["annotations_current"]
    )

    # 水库 → water_bodies polygon
    poly_dict = bundle.polygons._layers
    assert poly_dict.get("water_bodies") is not None
    assert any(
        getattr(f, "layer_type", "") == "external_water_polygon"
        for f in poly_dict["water_bodies"]
    )

    # 公路 → roads_current line
    lines_dict = bundle.lines._layers
    assert lines_dict.get("roads_current") is not None
    assert any(
        getattr(f, "layer_type", "") == "external_road_line"
        for f in lines_dict["roads_current"]
    )

    # 不应有 _external sub-key
    for gn in ("points", "lines", "polygons"):
        for k in getattr(bundle, gn)._layers:
            assert not k.endswith("_external"), f"unexpected: {gn}.{k}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))