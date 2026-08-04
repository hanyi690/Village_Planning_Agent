"""Shared fixtures for shared parse-compiler unit tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def land_use_report() -> dict:
    """Realistic L1 land_use report: content + INSTRUCTION."""
    return {
        "dimension_key": "land_use",
        "content": (
            "# 现状用地\n"
            "\n"
            "## 用地结构\n"
            "| 地类 | 面积(公顷) | 占比(%) |\n"
            "| --- | --- | --- |\n"
            "| 水田 | 120.0 | 46.2 |\n"
            "| 村庄建设用地 | 45.0 | 17.3 |\n"
            "\n"
            "## 控制线\n"
            "- 基本农田保护红线\n"
            "- 生态保护红线\n"
        ),
        "instruction": (
            "【INSTRUCTION】\n"
            "| 设施类型 | 数量 | 位置 |\n"
            "| --- | --- | --- |\n"
            "| 文化礼堂 | 1 | 村委会北侧 |\n"
        ),
        "summary": "",
        "report_id": "rpt-landuse-v1",
    }


@pytest.fixture
def socio_economic_report() -> dict:
    return {
        "dimension_key": "socio_economic",
        "content": (
            "# 社会经济\n"
            "\n"
            "## 人口\n"
            "村域人口 3200 人，12 个自然村。\n"
            "\n"
            "## 缺失数据\n"
            "- 各自然村常住人口\n"
        ),
        "instruction": "",
        "summary": "",
        "report_id": "rpt-socio-v1",
    }
