"""
Jintian Data API - 金田村标准数据静态 API

提供金田村真实 GIS 数据访问，用于测试页面对比基准。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()

# Data directory path
JINTIAN_DATA_DIR = Path(__file__).parent.parent.parent / "docs" / "gis" / "jintian_boundary"


# ============================================
# Helper Functions
# ============================================

def _load_geojson(filename: str) -> Dict:
    """Load GeoJSON file from jintian_boundary directory."""
    filepath = JINTIAN_DATA_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {filename}")

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_feature_count(geojson: Dict) -> int:
    """Get number of features in a GeoJSON."""
    return len(geojson.get("features", []))


def _get_geometry_types(geojson: Dict) -> List[str]:
    """Get unique geometry types in a GeoJSON."""
    types = set()
    for feature in geojson.get("features", []):
        geom = feature.get("geometry", {})
        if geom:
            types.add(geom.get("type", "Unknown"))
    return list(types)


# ============================================
# Metadata Endpoint
# ============================================

@router.get("/metadata")
async def get_jintian_metadata():
    """获取金田村元数据"""
    try:
        metadata = _load_geojson("metadata.json")
        return {
            "success": True,
            "data": metadata,
            "village_name": metadata.get("village", {}).get("name", "金田村委会"),
            "area_km2": metadata.get("village", {}).get("area_km2", 23.53),
            "coordinate_system": metadata.get("coordinate_system", "EPSG:4326"),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata file not found")
    except Exception as e:
        logger.error(f"[jintian_data] Failed to load metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# GeoJSON Data Endpoints
# ============================================

@router.get("/data/{filename}")
async def get_jintian_geojson(filename: str):
    """获取金田村标准 GeoJSON 数据

    Supported files:
    - boundary.geojson (规划边界)
    - boundary_current.geojson (现状边界)
    - road_current.geojson (现状道路)
    - road_planned.geojson (规划道路)
    - landuse_current.geojson (现状用地)
    - landuse_planned.geojson (规划用地)
    - geological_hazard_points.geojson (地质灾害点)
    - farmland_protection.geojson (农田保护红线)
    - ecological_protection.geojson (生态保护红线)
    - construction_zone.geojson (建设用地)
    - historical_protection.geojson (历史文化保护线)
    - admin_boundary_line.geojson (行政区划界线)
    - annotation_current.geojson (现状注记)
    - annotation_planned.geojson (规划注记)
    """
    # Ensure .geojson extension
    if not filename.endswith(".geojson") and not filename.endswith(".json"):
        filename = f"{filename}.geojson"

    try:
        geojson = _load_geojson(filename)
        feature_count = _get_feature_count(geojson)
        geometry_types = _get_geometry_types(geojson)

        return {
            "success": True,
            "filename": filename,
            "feature_count": feature_count,
            "geometry_types": geometry_types,
            "geojson": geojson,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except Exception as e:
        logger.error(f"[jintian_data] Failed to load {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# List Available Files
# ============================================

@router.get("/files")
async def list_jintian_files():
    """列出所有可用的金田村数据文件"""
    try:
        metadata = _load_geojson("metadata.json")
        files_info = metadata.get("files", {})

        file_list = []
        for filename, info in files_info.items():
            file_list.append({
                "filename": filename,
                "source_gdb": info.get("source_gdb", ""),
                "source_layer": info.get("source_layer", ""),
                "records": info.get("records", 0),
                "geometry_type": info.get("geometry_type", ""),
            })

        return {
            "success": True,
            "total_files": len(file_list),
            "files": file_list,
        }
    except Exception as e:
        logger.error(f"[jintian_data] Failed to list files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Report Content Endpoints
# ============================================

@router.get("/report/{layer}")
async def get_report_content(layer: int):
    """获取规划报告内容（用于替代 LLM 输入）

    layer: 1, 2, or 3
    """
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Layer must be 1, 2, or 3")

    report_path = JINTIAN_DATA_DIR.parent.parent / f"layer{layer}_完整报告.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report file not found: layer{layer}")

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "success": True,
            "layer": layer,
            "content": content,
            "word_count": len(content),
        }
    except Exception as e:
        logger.error(f"[jintian_data] Failed to read report layer{layer}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Extracted Planning Data
# ============================================

@router.get("/planning/facilities")
async def get_planning_facilities():
    """从 Layer3 报告提取规划设施信息"""
    try:
        report_path = JINTIAN_DATA_DIR.parent.parent / "layer3_完整报告.md"
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract facilities from report content
        facilities = []

        # Parse project table for facility info
        import re
        project_pattern = r'\| \*\*([^|]+)\*\* \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|'
        matches = re.findall(project_pattern, content)

        for match in matches:
            project_name = match[0].strip()
            if project_name:
                facilities.append({
                    "name": project_name,
                    "content": match[1].strip(),
                    "scale": match[2].strip(),
                    "location": match[3].strip(),
                    "function": match[4].strip(),
                })

        return {
            "success": True,
            "total": len(facilities),
            "facilities": facilities[:10],  # Return first 10 for summary
            "all_facilities": facilities,
        }
    except Exception as e:
        logger.error(f"[jintian_data] Failed to extract facilities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/planning/zones")
async def get_planning_zones():
    """从 Layer3 报告提取规划分区信息"""
    # Predefined zones based on "一心一带三区" structure
    zones = [
        {
            "zone_id": "Z01",
            "name": "综合服务中心",
            "type": "public_service",
            "description": "园寨村村委会及周边区域，集聚行政办公、电商物流、农产品加工、文化展示功能",
            "location_hint": "center",
            "area_ratio": 0.05,
        },
        {
            "zone_id": "Z02",
            "name": "南粤古驿道文旅发展带",
            "type": "tourism",
            "description": "沿南粤古驿道遗存及 Y122 乡道两侧，串联古檀树、古茶亭、祠堂等节点",
            "location_hint": "axis",
            "area_ratio": 0.10,
        },
        {
            "zone_id": "Z03",
            "name": "林下经济示范区",
            "type": "agricultural",
            "description": "村域内坡度平缓、无地质灾害隐患的商业林地，发展灵芝、黄精种植",
            "location_hint": "north",
            "area_ratio": 0.30,
        },
        {
            "zone_id": "Z04",
            "name": "特色农业种植区",
            "type": "agricultural",
            "description": "现有 85.2 公顷耕地集中区域，发展有机水稻、烤烟种植",
            "location_hint": "south",
            "area_ratio": 0.20,
        },
        {
            "zone_id": "Z05",
            "name": "生态康养保护区",
            "type": "ecological",
            "description": "生态林区域及地质灾害高风险区，以生态保护为主",
            "location_hint": "edge",
            "area_ratio": 0.35,
        },
    ]

    return {
        "success": True,
        "total": len(zones),
        "zones": zones,
        "structure": "一心一带三区",
    }


__all__ = ["router"]