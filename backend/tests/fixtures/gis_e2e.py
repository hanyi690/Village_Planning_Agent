"""GIS 端到端测试 fixtures — 真实金田村数据加载。

加载 docs/gis/jintian_boundary/ 的 GeoJSON 和 output/experiments/rag/g1/iter0/layer3_reports.json，
转成 PlanningKG.build_from_reports 期望的格式 {dim_key: {"summary": {"metrics": {...}}, "content": "..."}}。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

# 项目根目录（backend/ 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
JINTIAN_DIR = PROJECT_ROOT / "docs" / "gis" / "jintian_boundary"
L3_REPORT_PATH = PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"


def _load_geojson(path: Path) -> Dict[str, Any]:
    """加载 GeoJSON 文件。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_landuse_current() -> Dict[str, Any]:
    """加载现状用地图斑（660 个地块，含 DLBM/DLMC/DLMJ）。"""
    return _load_geojson(JINTIAN_DIR / "landuse_current.geojson")


def load_boundary() -> Dict[str, Any]:
    """加载村界边界（1 个 MultiPolygon，MJ=2352.89ha）。"""
    return _load_geojson(JINTIAN_DIR / "boundary.geojson")


def load_protection_zones() -> Dict[str, Dict[str, Any]]:
    """加载保护约束区域字典。

    Returns:
        {"farmland": {...}, "ecological": {...}, "historical": {...}}
    """
    return {
        "farmland": _load_geojson(JINTIAN_DIR / "farmland_protection.geojson"),
        "ecological": _load_geojson(JINTIAN_DIR / "ecological_protection.geojson"),
        "historical": _load_geojson(JINTIAN_DIR / "historical_protection.geojson"),
    }


def load_road_current() -> Dict[str, Any]:
    """加载现状道路（131 条 MultiLineString）。"""
    return _load_geojson(JINTIAN_DIR / "road_current.geojson")


def load_construction_zone() -> Dict[str, Any]:
    """加载建设区（139 个 MultiPolygon）。"""
    return _load_geojson(JINTIAN_DIR / "construction_zone.geojson")


def load_hazard_points() -> Dict[str, Any]:
    """加载地质灾害点（40 个 Point）。"""
    return _load_geojson(JINTIAN_DIR / "geological_hazard_points.geojson")


def load_l3_reports_raw() -> Dict[str, str]:
    """加载 L3 报告原始字符串。

    Returns:
        {dim_key: "<markdown 字符串>"} — 12 个维度
    """
    with open(L3_REPORT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("reports", {})


def _extract_metrics_regex(content: str) -> Dict[str, Any]:
    """纯 regex 提取数值指标，复用 summary.generator 的逻辑（不依赖 LLM）。"""
    import re

    metrics: Dict[str, Any] = {}
    patterns = [
        (r'([\d.]+)\s*公顷', 'area_ha'),
        (r'([\d.]+)\s*亩', 'area_mu'),
        (r'(\d+)\s*人', 'population'),
        (r'(\d+)\s*户', 'households'),
        (r'([\d.]+)\s*%', 'percentage'),
        (r'([\d.]+)\s*万元', 'amount_wan_yuan'),
        (r'([\d.]+)\s*km', 'length_km'),
        (r'([\d.]+)\s*m[²2]', 'area_sqm'),
    ]
    for pat, key in patterns:
        m = re.search(pat, content)
        if m:
            val = m.group(1)
            metrics[key] = float(val) if '.' in val else int(val)

    # 从土地利用规划报告提取特定指标
    if "建设用地" in content and "公顷" in content:
        m = re.search(r'建设用地.*?([\d.]+)\s*公顷', content)
        if m:
            metrics["建设用地规模_公顷"] = float(m.group(1))
    if "耕地" in content and "公顷" in content:
        m = re.search(r'耕地.*?([\d.]+)\s*公顷', content)
        if m:
            metrics["耕地保有量_公顷"] = float(m.group(1))
    if "生态保护红线" in content:
        m = re.search(r'生态保护红线.*?([\d.]+)\s*公顷', content)
        if m:
            metrics["生态保护红线面积"] = float(m.group(1))
    if "永久基本农田" in content:
        m = re.search(r'永久基本农田.*?([\d.]+)\s*公顷', content)
        if m:
            metrics["永久基本农田_公顷"] = float(m.group(1))
    if "森林覆盖率" in content:
        m = re.search(r'森林覆盖率.*?([\d.]+)\s*%', content)
        if m:
            metrics["森林覆盖率_百分比"] = float(m.group(1))
    if "林地" in content and "公顷" in content:
        m = re.search(r'林地.*?([\d.]+)\s*公顷', content)
        if m:
            metrics["林地保有量_公顷"] = float(m.group(1))

    return metrics


def load_l3_reports_for_kg() -> Dict[str, Dict[str, Any]]:
    """加载 L3 报告并转成 PlanningKG 期望的格式。

    Returns:
        {dim_key: {"summary": {"metrics": {...}}, "content": "<markdown 字符串>"}}
    """
    raw = load_l3_reports_raw()
    result = {}
    for dim_key, content in raw.items():
        if not isinstance(content, str):
            continue
        result[dim_key] = {
            "summary": {"metrics": _extract_metrics_regex(content)},
            "content": content,
        }
    return result


def load_gis_data_for_agent() -> Dict[str, Optional[Dict[str, Any]]]:
    """加载所有 GIS 数据，构造 gis_agent_node 期望的 gis_data 字典。"""
    return {
        "boundary_geojson": load_boundary(),
        "landuse_current_geojson": load_landuse_current(),
        "protection_zones": load_protection_zones(),
        "road_geojson": load_road_current(),
        "construction_zone_geojson": load_construction_zone(),
        "hazard_points_geojson": load_hazard_points(),
    }


def make_real_intent() -> Dict[str, Any]:
    """构造真实规划意图（4 个 ZoneIntent），用于 generate_layout。"""
    return {
        "zones": [
            {
                "zone_id": "z_farm",
                "land_use": "农业用地",
                "dlbm": "0110",
                "area_ratio": 0.03,
                "direction": "center",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_build",
                "land_use": "居住用地",
                "dlbm": "2121",
                "area_ratio": 0.013,
                "direction": "center",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_eco",
                "land_use": "生态绿地",
                "dlbm": "0300",
                "area_ratio": 0.15,
                "direction": "periphery",
                "preserve_existing": True,
            },
            {
                "zone_id": "z_agri",
                "land_use": "农业用地",
                "dlbm": "0200",
                "area_ratio": 0.80,
                "direction": "periphery",
                "preserve_existing": True,
            },
        ],
        "metadata": {
            "spatial_structure": "一核两带三区",
            "total_area_ha": 2352.56,
            "farmland_ha": 78.83,
            "construction_ha": 30.50,
            "ecological_ha": 362.02,
            "general_agriculture_ha": 1881.54,
        },
    }


# ============================================
# pytest fixtures
# ============================================

@pytest.fixture(scope="module")
def landuse_geojson() -> Dict[str, Any]:
    return load_landuse_current()


@pytest.fixture(scope="module")
def boundary_geojson() -> Dict[str, Any]:
    return load_boundary()


@pytest.fixture(scope="module")
def protection_zones() -> Dict[str, Dict[str, Any]]:
    return load_protection_zones()


@pytest.fixture(scope="module")
def road_geojson() -> Dict[str, Any]:
    return load_road_current()


@pytest.fixture(scope="module")
def construction_zone_geojson() -> Dict[str, Any]:
    return load_construction_zone()


@pytest.fixture(scope="module")
def hazard_points_geojson() -> Dict[str, Any]:
    return load_hazard_points()


@pytest.fixture(scope="module")
def l3_reports_for_kg() -> Dict[str, Dict[str, Any]]:
    return load_l3_reports_for_kg()


@pytest.fixture(scope="module")
def gis_data() -> Dict[str, Optional[Dict[str, Any]]]:
    return load_gis_data_for_agent()


@pytest.fixture(scope="module")
def real_intent() -> Dict[str, Any]:
    return make_real_intent()
