"""Migrated text_parser + extract_instruction_tables tests."""

from app.modules.parsing.text_parser import parse, ParseResult
from app.modules.parsing.tables import extract_instruction_tables


def test_parse_empty_text():
    result = parse("", village_name="测试村")
    assert isinstance(result, ParseResult)
    assert result.intent.village_name == "测试村"


def test_parse_extracts_zones():
    text = "规划分区：村庄建设区 面积：50%"
    result = parse(text, village_name="测试村")
    assert len(result.intent.zone_targets) >= 1


def test_parse_async_is_callable():
    import asyncio
    from app.modules.parsing.text_parser import parse_async

    result = asyncio.run(parse_async("测试文本", village_name="测试村"))
    assert isinstance(result, ParseResult)


def test_extract_instruction_tables_empty():
    result = extract_instruction_tables("")
    assert result == {"projects": [], "zones": [], "facilities": [], "axes": [], "roads": []}


def test_extract_instruction_tables_with_section():
    text = """【INSTRUCTION】
| 类型 | 名称 | 位置 | 描述 |
| :--- | :--- | :--- | :--- |
| 项目 | 新建文化广场 | 村中心 | 文化活动 |
| 分区 | 农田保护区 | 村北部 | 耕地保护 |
"""
    result = extract_instruction_tables(text)
    assert len(result["projects"]) == 1
    assert result["projects"][0].name == "新建文化广场"
    assert len(result["zones"]) == 1
    assert result["zones"][0].land_use == "农田保护区"


def test_resolve_spatial_anchors_importable():
    from app.modules.spatial_ops.grounding.resolver import resolve_spatial_anchors
    assert callable(resolve_spatial_anchors)
