"""P8 单测：INSTRUCTION 段结构化提取 + 自然村→BSM 解析 + 位置列提取。"""

from unittest.mock import MagicMock, patch

from app.agent.gis.parse import parse
from app.agent.gis.parse.agent import (
    _extract_instruction_tables,
    _extract_location_tokens,
    resolve_spatial_anchors,
)
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    SpatialPlanningIntent,
)

INSTRUCTION_TABLE = """【INSTRUCTION】（内部指令段，仅供下游 GIS 空间定位解析）
| 类型 | 名称 | 位置 | 描述 | 规模 |
| :--- | :--- | :--- | :--- | :--- |
| 项目 | 南粤古驿道重点段修复工程 | 肩丰至炉池段 | 古驿道遗存保护修复与路面平整 | 1500m |
| 功能分区 | 田园生活区 | 村中部 | 宅基地集中建设集约发展 | - |
| 设施 | 公共厕所 | 肩丰、炉池、田坑 | 与文化广场配套建设 | 3座 |
| 轴线 | 旅游休闲轴 | 沿金田河 | 森林康养与休闲农业集聚带 | - |
"""


def test_instruction_zones_facilities_axes():
    r = _extract_instruction_tables(INSTRUCTION_TABLE)
    assert len(r["zones"]) == 1
    assert r["zones"][0].land_use == "田园生活区"
    assert r["zones"][0].spatial_preference.reference == "村中部"
    assert len(r["facilities"]) == 1
    assert r["facilities"][0].type == "公共厕所"
    assert r["facilities"][0].location_hint == "肩丰、炉池、田坑"
    assert r["facilities"][0].anchor_village == "肩丰、炉池、田坑"
    assert len(r["axes"]) == 1
    assert r["axes"][0].label == "旅游休闲轴"
    assert r["axes"][0].reference_feature == "沿金田河"


def test_instruction_bad_rows_skipped():
    text = INSTRUCTION_TABLE + """| 坏行 | | | | |
| 未知类型 | 乱数据 | 园寨 | bad | - |
| 设施 |  | 园寨 | 空名称丢弃 | - |
"""
    r = _extract_instruction_tables(text)
    assert len(r["facilities"]) == 1  # 空名称行被丢弃


def test_instruction_marker_absent_returns_empty():
    r = _extract_instruction_tables("无 INSTRUCTION 段")
    assert r == {"zones": [], "facilities": [], "axes": []}


def test_parse_merges_instruction_with_tables():
    text = ZONE_TABLE = """【功能分区表】
| 分区名称 | 面积(公顷) | 占比(%) | 位置 | 管控要求 |
| :--- | :--- | :--- | :--- | :--- |
| 生态保护区 | 362.02 | 15.39 | 金田村西部 | 严格保护 |
""" + "\n" + INSTRUCTION_TABLE
    result = parse(text, village_name="金田村")
    zone = next(zt for zt in result.intent.zone_targets if zt.land_use == "生态保护区")
    # 表格位置列 → spatial_preference.reference
    assert zone.spatial_preference.reference == "金田村西部"
    # INSTRUCTION 设施并入（不重复）
    assert any(f.type == "公共厕所" for f in result.intent.facilities)
    assert any(a.label == "旅游休闲轴" for a in result.intent.development_axes)


def test_zone_table_location_column_extracted():
    text = """【空间结构分区表】
| 分区类型 | 面积(公顷) | 位置 | 功能定位 |
| :--- | :--- | :--- | :--- |
| 田园生活区 | 120.00 | 金田村中部 | 村民聚居 |
"""
    result = parse(text, village_name="金田村")
    assert any(
        zt.land_use == "田园生活区"
        and zt.spatial_preference is not None
        and zt.spatial_preference.reference == "金田村中部"
        for zt in result.intent.zone_targets
    )


def test_project_table_loose_header():
    text = """【产业项目清单】
| 工程名称 | 建设内容 | 建设规模 | 选址位置 | 实施期限 |
| :--- | :--- | :--- | :--- | :--- |
| 林芝规模化种植基地 | 土地平整、大棚建设 | 80亩 | 园寨、田坑 | 2026-2028 |
"""
    result = parse(text, village_name="金田村")
    projects = {f.type: f.location_hint for f in result.intent.facilities}
    assert projects.get("林芝规模化种植基地") == "园寨、田坑"


def test_location_tokens_splitting():
    assert _extract_location_tokens("肩丰、炉池、田坑") == ["肩丰", "炉池", "田坑"]
    assert _extract_location_tokens("肩丰至炉池段") == ["肩丰", "炉池"]
    assert _extract_location_tokens("园寨自然村") == ["园寨"]


def test_zone_regex_does_not_match_prose_with_trailing_numbers():
    """P3-6: 正文长句（逗号分隔 + 尾部数字）不得误提取为分区目标。"""
    from app.agent.gis.parse.agent import _extract_zone_targets

    text = """【产业发展定位】
核心目标：至规划期末实现农业总产值翻番，旅游年接待游客突破5万人次。
【土地利用规划】
| 分区名称 | 面积(公顷) | 占比(%) |
| :--- | :--- | :--- |
| 村庄建设区 | 30.50 | 1.30 |
"""
    zones = _extract_zone_targets(text)
    assert not any("至规划期末" in (z.land_use or "") for z in zones)


def test_direction_from_location():
    from app.agent.gis.parse.agent import _direction_from_location

    assert _direction_from_location("村中部") == "center"
    assert _direction_from_location("村东北部与西南部") == "northeast"
    assert _direction_from_location("金田村西部") == "west"
    assert _direction_from_location("沿金田河") == ""
    assert _direction_from_location("园寨") == ""


def test_resolve_spatial_anchors_fills_candidate_bsms():
    entry = MagicMock()
    entry.bsms = ["BSM001", "BSM002"]
    gaz = MagicMock()
    gaz.entries = [entry]
    gaz.resolve.side_effect = lambda n, fuzzy=True: entry

    intent = SpatialPlanningIntent()
    intent.facilities.append(FacilityTarget(type="公厕", location_hint="肩丰"))

    with patch("app.modules.kg.gazetteer.load_gazetteer", return_value=gaz) as m:
        n = resolve_spatial_anchors(intent, village_name="jintian")
    m.assert_called_once_with("jintian")
    assert n == 1
    assert intent.facilities[0].candidate_bsms == ["BSM001", "BSM002"]


def test_resolve_spatial_anchors_no_gazetteer():
    intent = SpatialPlanningIntent()
    intent.facilities.append(FacilityTarget(type="公厕", location_hint="肩丰"))
    with patch("app.modules.kg.gazetteer.load_gazetteer", return_value=MagicMock(entries=[])):
        n = resolve_spatial_anchors(intent, village_name="jintian")
    assert n == 0
    assert intent.facilities[0].candidate_bsms == []
