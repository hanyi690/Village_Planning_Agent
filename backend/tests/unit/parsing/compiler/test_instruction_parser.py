"""Tests for instruction_parser - 【INSTRUCTION】 table extraction."""
from __future__ import annotations

from app.modules.parsing.compiler.instruction_parser import (
    parse_instruction_tables,
    split_content_instruction,
)


def test_split_content_instruction():
    content, instruction = split_content_instruction(
        "# 报告\n内容正文\n【INSTRUCTION】\n| 设施 | 数量 |\n"
    )
    assert "内容正文" in content
    assert "设施" in instruction
    assert "【INSTRUCTION】" not in content


def test_split_content_instruction_no_marker():
    content, instruction = split_content_instruction("# 报告\n无指令")
    assert content == "# 报告\n无指令"
    assert instruction == ""


def test_parse_instruction_tables_facility_rows():
    instruction = (
        "【INSTRUCTION】\n"
        "| 设施类型 | 数量 | 位置 |\n"
        "| --- | --- | --- |\n"
        "| 文化礼堂 | 1 | 村委会北侧 |\n"
    )
    parsed = parse_instruction_tables(instruction)
    assert "facility_rows" in parsed
    assert len(parsed["facility_rows"]) == 1
    assert parsed["facility_rows"][0]["设施类型"] == "文化礼堂"


def test_parse_instruction_tables_empty():
    assert parse_instruction_tables("") == {}


def test_parse_instruction_tables_l1_location_contract():
    parsed = parse_instruction_tables(
        "【INSTRUCTION】\n"
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 现状项目 | 村庄公共服务 | 金田村 | 公共服务设施集中 | 1处 |\n"
    )
    assert parsed["l1_rows"][0]["位置"] == "金田村"
