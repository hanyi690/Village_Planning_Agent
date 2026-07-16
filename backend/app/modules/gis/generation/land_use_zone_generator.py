"""Land Use Zone Generator — 土地用途分区 V/N/E classification.

Generates the land_use_zone layer (layer 11) following the Ministry of Housing
and Urban-Rural Development's "Village Planning Land Use Classification Guide"
(住建部《村庄规划用地分类指南》), as directly referenced by Guangdong Appendix E.

Hierarchy: 3大类 (V/N/E) → 10中类 → 15小类

V  村庄建设用地
  V1  村民住宅用地
    V11 住宅用地, V12 混合式住宅用地
  V2  村庄公共服务用地
    V21 村庄公共服务设施用地, V22 村庄公共场地
  V3  村庄产业用地
    V31 村庄商业服务业设施用地, V32 村庄生产仓储用地
  V4  村庄基础设施用地
    V41 村庄道路用地, V42 村庄交通设施用地, V43 村庄公用设施用地
  V9  村庄其他建设用地

N  非村庄建设用地
  N1  对外交通设施用地
  N2  国有建设用地

E  非建设用地
  E1  水域 (E11 自然水域, E12 水库, E13 坑塘沟渠)
  E2  农林用地 (E21 设施农用地, E22 农用道路, E23 其他农林用地)
  E9  其他非建设用地

Mapping chain: DLBM (三调) → GHFLBM/GHYTBM (规划分类) → V/N/E
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False

# V/N/E classification tree — single source of truth
VNE_CLASSIFICATION: Dict[str, Dict[str, Any]] = {
    # ── V: 村庄建设用地 ──
    "V": {
        "name": "村庄建设用地", "parent": None, "color": "#FDEBD0",
        "children": {
            "V1": {
                "name": "村民住宅用地", "parent": "V", "color": "#FAD7A1",
                "children": {
                    "V11": {"name": "住宅用地", "parent": "V1", "description": "农村宅基地"},
                    "V12": {"name": "混合式住宅用地", "parent": "V1", "description": "商住混合"},
                },
            },
            "V2": {
                "name": "村庄公共服务用地", "parent": "V", "color": "#D5F5E3",
                "children": {
                    "V21": {"name": "村庄公共服务设施用地", "parent": "V2",
                            "description": "村委会/学校/卫生站/文化站"},
                    "V22": {"name": "村庄公共场地", "parent": "V2",
                            "description": "广场/小绿地"},
                },
            },
            "V3": {
                "name": "村庄产业用地", "parent": "V", "color": "#F9E79F",
                "children": {
                    "V31": {"name": "村庄商业服务业设施用地", "parent": "V3",
                            "description": "小超市/集贸市场/旅游接待"},
                    "V32": {"name": "村庄生产仓储用地", "parent": "V3",
                            "description": "手工业/食品加工/仓库"},
                },
            },
            "V4": {
                "name": "村庄基础设施用地", "parent": "V", "color": "#D6EAF8",
                "children": {
                    "V41": {"name": "村庄道路用地", "parent": "V4"},
                    "V42": {"name": "村庄交通设施用地", "parent": "V4",
                            "description": "停车场/公交站点"},
                    "V43": {"name": "村庄公用设施用地", "parent": "V4",
                            "description": "给排水/供电/公厕/垃圾站/消防"},
                },
            },
            "V9": {"name": "村庄其他建设用地", "parent": "V",
                   "description": "未利用/待研究的集体建设用地"},
        },
    },
    # ── N: 非村庄建设用地 ──
    "N": {
        "name": "非村庄建设用地", "parent": None, "color": "#E8DAEF",
        "children": {
            "N1": {"name": "对外交通设施用地", "parent": "N",
                   "description": "过境公路/铁路"},
            "N2": {"name": "国有建设用地", "parent": "N",
                   "description": "公用设施/特殊用地/采矿用地"},
        },
    },
    # ── E: 非建设用地 ──
    "E": {
        "name": "非建设用地", "parent": None, "color": "#D5F5E3",
        "children": {
            "E1": {
                "name": "水域", "parent": "E", "color": "#AED6F1",
                "children": {
                    "E11": {"name": "自然水域", "parent": "E1"},
                    "E12": {"name": "水库", "parent": "E1"},
                    "E13": {"name": "坑塘沟渠", "parent": "E1"},
                },
            },
            "E2": {
                "name": "农林用地", "parent": "E", "color": "#ABEBC6",
                "children": {
                    "E21": {"name": "设施农用地", "parent": "E2",
                            "description": "畜禽舍/大棚/晾晒场"},
                    "E22": {"name": "农用道路", "parent": "E2",
                            "description": "机耕道/林道"},
                    "E23": {"name": "其他农林用地", "parent": "E2",
                            "description": "耕地/园地/林地/牧草地/田坎"},
                },
            },
            "E9": {"name": "其他非建设用地", "parent": "E",
                   "description": "空闲地/盐碱地/沼泽地/裸地"},
        },
    },
}


def flatten_vne_codes() -> Dict[str, Dict[str, str]]:
    """Flatten VNE tree → flat dict {code: {name, parent, level}}."""
    result = {}
    for top_code, top_info in VNE_CLASSIFICATION.items():
        result[top_code] = {"name": top_info["name"], "parent": "", "level": "大类"}
        for mid_code, mid_info in top_info.get("children", {}).items():
            result[mid_code] = {"name": mid_info["name"], "parent": top_code, "level": "中类"}
            for sub_code, sub_info in mid_info.get("children", {}).items():
                result[sub_code] = {"name": sub_info["name"], "parent": mid_code, "level": "小类"}
    return result


# DLBM → VNE mapping (derived from GHFLBM/GHYTBM bridge)
# Populated from zone_schema encodings where available, otherwise from empirical data
def _build_dlbm_to_vne() -> Dict[str, str]:
    """Build DLBM → VNE classification code mapping.

    Derivation chain: DLBM → GHYTBM → VNE
    Falls back to zone_type → VNE heuristic when GHYTBM unavailable.
    """
    from app.modules.gis.schema import GHYTBM_TO_VNE, DLBM_TO_ZONE_TYPE, VNE_TO_ZONE_TYPE

    mapping: Dict[str, str] = {}

    # Prefer GHYTBM → VNE direct lookup
    for ghytbm, vne in GHYTBM_TO_VNE.items():
        # Find DLBM codes that map to this GHYTBM
        pass  # GHYTBM_TO_VNE already has the mapping

    # Fallback heuristic: DLBM zone_type → VNE
    zone_to_vne = {v: k for k, v in VNE_TO_ZONE_TYPE.items()} if VNE_TO_ZONE_TYPE else {}

    for dlbm, zone_type in DLBM_TO_ZONE_TYPE.items():
        if dlbm in mapping:
            continue  # already mapped via GHYTBM
        if zone_type == "农业用地":
            mapping[dlbm] = "E23"  # 其他农林用地
        elif zone_type in ("林业用地", "生态绿地"):
            mapping[dlbm] = "E23"
        elif zone_type == "水域":
            mapping[dlbm] = "E13"  # 坑塘沟渠
        elif zone_type == "居住用地":
            mapping[dlbm] = "V11"  # 住宅用地
        elif zone_type == "产业用地":
            mapping[dlbm] = "V32"  # 村庄生产仓储用地
        elif zone_type == "公共服务用地":
            mapping[dlbm] = "V21"  # 村庄公共服务设施用地
        elif zone_type == "基础设施用地":
            mapping[dlbm] = "V43"  # 村庄公用设施用地
        elif zone_type in ("商业用地",):
            mapping[dlbm] = "V31"  # 村庄商业服务业设施用地
        else:
            mapping[dlbm] = "E23"  # default fallback

    return mapping


# Module-level singleton
_DLBM_TO_VNE: Optional[Dict[str, str]] = None


def get_dlbm_to_vne() -> Dict[str, str]:
    global _DLBM_TO_VNE
    if _DLBM_TO_VNE is None:
        _DLBM_TO_VNE = _build_dlbm_to_vne()
    return _DLBM_TO_VNE


class LandUseZoneGenerator:
    """Generate V/N/E land use zone layer from planned landuse.

    Mapping chain: DLBM → GHYTBM → V/N/E code
    Fallback: DLBM → zone_type → V/N/E code (heuristic)

    Output: GeoJSON FeatureCollection with YTDLDM (用途地类代码) and YTDLMC (名称).
    """

    def generate(
        self,
        allocated_geojson: Optional[Dict[str, Any]] = None,
        current_landuse: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate V/N/E land use zone GeoJSON.

        Uses allocated_geojson (planned) when available,
        falls back to current_landuse.

        Returns FeatureCollection with properties:
          - YTDLDM: V/N/E code (V11, E23, N1, etc.)
          - YTDLMC: V/N/E name (住宅用地, 其他农林用地, etc.)
        """
        geojson = allocated_geojson or current_landuse
        if not geojson or not geojson.get("features"):
            return {"type": "FeatureCollection", "features": []}

        dlbm_to_vne = get_dlbm_to_vne()
        vne_flat = flatten_vne_codes()

        try:
            import geopandas as gpd
            from shapely.ops import unary_union

            features_out = []
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                dlbm = str(props.get("DLBM", props.get("dlbm", "")))
                ghytbm = str(props.get("GHYTBM", ""))

                # Determine VNE code
                vne_code = ""
                if ghytbm:
                    from app.modules.gis.schema import GHYTBM_TO_VNE
                    vne_code = GHYTBM_TO_VNE.get(ghytbm, "")
                if not vne_code:
                    vne_code = dlbm_to_vne.get(dlbm, "E23")

                vne_info = vne_flat.get(vne_code, {"name": "其他", "parent": "E"})

                features_out.append({
                    "type": "Feature",
                    "geometry": feat.get("geometry", {}),
                    "properties": {
                        **props,
                        "YTDLDM": vne_code,
                        "YTDLMC": vne_info["name"],
                        "VNE_LEVEL": vne_info.get("level", ""),
                        "VNE_PARENT": vne_info.get("parent", ""),
                    },
                })

            logger.info(
                "[LandUseZoneGenerator] Generated %d V/N/E features",
                len(features_out),
            )
            return {"type": "FeatureCollection", "features": features_out}

        except Exception as e:
            logger.error("[LandUseZoneGenerator] Generation failed: %s", e)
            return {"type": "FeatureCollection", "features": []}


__all__ = ["LandUseZoneGenerator", "VNE_CLASSIFICATION", "flatten_vne_codes", "get_dlbm_to_vne"]
