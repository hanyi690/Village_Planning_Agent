"""
GDB schema: layer registry, field definitions, and naming conventions.

Single source of truth for:
  - GDB layer names (provincial naming convention)
  - Field structures per layer (derived from 金田村 reference GDB)
  - Internal LayerType → GDB layer mapping
  - Naming rules: {prefix}_{description}_{feature_type_code}_{date}
    Feature type codes: PBL=面(polygon), LJJ=线(line), DMM=点(point)

All field definitions are based on actual GDB data from:
  - docs/references/村庄规划总图/金田村村庄规划工程文件/1.村庄用地现状图/图层.gdb
  - docs/references/村庄规划总图/金田村村庄规划工程文件/2.村庄规划总图/图层.gdb
"""

from typing import Any, Dict, List, Optional, Tuple

# Type alias for field spec: (name, dtype)
GdbFieldSpec = Tuple[str, str]
# Type alias for layer definition
LayerDef = Dict[str, Any]


# ============================================
# GDB Naming Convention
# ============================================

# Feature type codes (要素类型代码)
FEATURE_TYPE_CODES = {
    "polygon": "PBL",   # 面
    "line": "LJJ",      # 线
    "point": "DMM",     # 点 (注记也用LJJ在部分规范中，但金田实测用LJJ)
}

# Default prefix (first 2 chars of XZQHDM county-level code)
# 金田村: 441426108004 → prefix "JT" (金田)
DEFAULT_GDB_PREFIX = "JT"

# Default date format: YYYYMMDD (同参考GDB中的日期后缀)
DEFAULT_GDB_DATE = "20221212"


def make_gdb_layer_name(
    description: str,
    feature_type: str,
    prefix: str = DEFAULT_GDB_PREFIX,
    date: str = DEFAULT_GDB_DATE,
) -> str:
    """Build a GDB layer name following provincial convention.

    Example: make_gdb_layer_name("行政区划", "polygon") → "JT_行政区划_PBL_20221212"
    """
    code = FEATURE_TYPE_CODES.get(feature_type, "PBL")
    return f"{prefix}_{description}_{code}_{date}"


# ============================================
# GDB Layer Registry — 12 layers (5 current + 7 planned)
# ============================================

GDB_LAYER_REGISTRY: Dict[str, LayerDef] = {
    # ── 现状要素层 (5 layers) ──────────────────────────────

    "admin_area": {
        "gdb_name_template": "{prefix}_行政区划_PBL_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BSM", "int16"),        # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("DJZQMC", "str:50"),    # 登记区划名称
            ("DJZQDM", "str:12"),    # 登记区划代码
            ("MJ", "float32"),       # 面积
            ("BZ", "str:255"),       # 备注
        ],
        "source": "current/boundary.geojson",
        "internal_layer": "boundary",
        "category": "current",
        "description": "行政村行政区划面",
    },

    "admin_boundary_line": {
        "gdb_name_template": "{prefix}_行政区划界线_LJJ_{date}",
        "geometry": "MultiLineString",
        "fields": [
            ("BSM", "int16"),        # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("DJZQDM", "str:12"),    # 登记区划代码
            ("界线类型", "int32"),    # 界线类型代码 (670500=村界)
            ("界线说明", "str:20"),   # 界线说明文字
        ],
        "source": "current/admin_boundary_line.geojson",
        "internal_layer": "boundary",
        "category": "current",
        "description": "行政区划界线",
    },

    "current_landuse": {
        "gdb_name_template": "{prefix}_现状地类图斑_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BSM", "str:18"),       # 标识码 (18位元素代码)
            ("YSDM", "str:10"),      # 要素代码
            ("DLBM", "str:4"),       # 地类编码 (GB/T 21010)
            ("DLMC", "str:20"),      # 地类名称
            ("SDDLBM", "str:5"),     # 三调地类编码 (部分GDB缺失, DLBM≈SDDLBM可替代)
            ("SDDLMC", "str:60"),    # 三调地类名称 (部分GDB缺失)
            ("DLMJ", "float64"),     # 地类面积
        ],
        "source": "current/landuse.geojson",
        "internal_layer": "function_zone",
        "category": "current",
        "description": "基期年现状地类图斑",
    },

    "current_road": {
        "gdb_name_template": "{prefix}_农村居民点外道路_LJJ_{date}",
        "geometry": "MultiLineString",
        "fields": [
            ("Shape_Length", "float64"),
        ],
        "source": "current/road.geojson",
        "internal_layer": "infrastructure",
        "category": "current",
        "description": "现状道路",
    },

    "current_annotation": {
        "gdb_name_template": "{prefix}_现状注记_LJJ_{date}",
        "geometry": "Point",
        "fields": [
            ("注记", "str:100"),     # 注记文字
            ("分类", "str:20"),      # 注记分类 (现状设施点/地名等)
        ],
        "source": "current/annotation.geojson",
        "internal_layer": "annotation",
        "category": "current",
        "description": "现状注记",
    },

    # ── 规划要素层 (7 layers) ──────────────────────────────

    "planned_landuse": {
        "gdb_name_template": "{prefix}_期末地类_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("MS", "str:10"),        # 描述
            ("BSM", "str:18"),       # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("TBH", "str:10"),       # 图斑号
            ("XZQHDM", "str:12"),    # 行政区划代码
            ("XZQHMC", "str:50"),    # 行政区划名称
            ("DLBM", "str:4"),       # 地类编码(现状)
            ("DLMJ", "float64"),     # 地类面积
            ("QMDLBM", "str:4"),     # 期末地类编码
            ("LYYSDM", "str:10"),    # 来源要素代码
            ("GHFLBM", "str:4"),     # 规划分类编码
            ("QMGHFLBM", "str:4"),   # 期末规划分类编码
            ("GHYTBM", "str:4"),     # 规划用途编码
            ("GHYTMC", "str:20"),    # 规划用途名称
            ("Shape_Length", "float64"),  # 几何周长
            ("Shape_Area", "float64"),    # 几何面积
        ],
        "source": "planned/landuse.geojson",
        "internal_layer": "function_zone",
        "category": "planned",
        "description": "目标年期末地类图斑(含规划分类编码)",
    },

    "ecological_redline": {
        "gdb_name_template": "{prefix}_生态保护红线_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("OBJECTID", "int32"),   # 对象ID
            ("区县", "str:20"),      # 所属区县
            ("分带", "float64"),     # 分带号
            ("地市", "str:20"),      # 所属地市
            ("MJ", "float64"),       # 面积
        ],
        "source": "planned/ecological_protection.geojson",
        "internal_layer": "ecological_redline",
        "category": "planned",
        "description": "生态保护红线",
    },

    "farmland_protection": {
        "gdb_name_template": "{prefix}_永久基本农田保护红线_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("YSDM", "str:10"),      # 要素代码
            ("XZQHDM", "str:12"),    # 行政区划代码
            ("XZQHMC", "str:50"),    # 行政区划名称
            ("BSM", "str:18"),       # 标识码
            ("JBNT_MJ", "float64"),  # 基本农田面积
        ],
        "source": "planned/farmland_protection.geojson",
        "internal_layer": "farmland_protection",
        "category": "planned",
        "description": "永久基本农田保护红线",
    },

    "historical_protection": {
        "gdb_name_template": "{prefix}_历史文化保护线_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BUFF_DIST", "float64"),  # 缓冲距离
            ("ORIG_FID", "float64"),   # 原始要素ID
        ],
        "source": "planned/historical_protection.geojson",
        "internal_layer": "historical_protection",
        "category": "planned",
        "description": "历史文化保护线",
    },

    "construction_zone": {
        "gdb_name_template": "{prefix}_有条件建设区_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BSM", "str:18"),       # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("BH", "str:20"),        # 编号
            ("XZQHDM", "str:12"),    # 行政区划代码
            ("XZQHM", "str:50"),     # 行政区划名称
            ("LX", "str:20"),        # 类型 (有条件建设区)
            ("MJ", "float64"),       # 面积
        ],
        "source": "planned/construction_zone.geojson",
        "internal_layer": "construction_zone",
        "category": "planned",
        "description": "有条件建设区",
    },

    "space_control_zone": {
        "gdb_name_template": "{prefix}_建设用地空间管制区_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BSM", "str:18"),       # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("XZQHDM", "str:12"),    # 行政区划代码
            ("XZQHMC", "str:50"),    # 行政区划名称
            ("GZQLX", "str:4"),      # 管制区类型代码 (510/520/530/540)
            ("GZQLXMC", "str:30"),   # 管制区类型名称
            ("MJ", "float64"),       # 面积
        ],
        "source": "planned/space_control_zone.geojson",
        "internal_layer": "space_control_zone",
        "category": "planned",
        "description": "建设用地空间管制区 (允许510/限制520/有条件530/禁止540)",
    },

    "land_use_zone": {
        "gdb_name_template": "{prefix}_土地用途分区_LJJ_{date}",
        "geometry": "MultiPolygon",
        "fields": [
            ("BSM", "str:18"),       # 标识码
            ("YSDM", "str:10"),      # 要素代码
            ("XZQHDM", "str:12"),    # 行政区划代码
            ("XZQHMC", "str:50"),    # 行政区划名称
            ("YTDLDM", "str:4"),     # 用途地类代码 (V11/V12/N1/E1等)
            ("YTDLMC", "str:50"),    # 用途地类名称
            ("MJ", "float64"),       # 面积
        ],
        "source": "planned/land_use_zone.geojson",
        "internal_layer": "land_use_zone",
        "category": "planned",
        "description": "土地用途分区 (V/N/E 三大类体系, 住建部标准)",
    },

    "hazard_points": {
        "gdb_name_template": "{prefix}_地质灾害点_LJJ_{date}",
        "geometry": "Point",
        "fields": [
            ("地质灾害点名称", "str:100"),
            ("纬度", "str:30"),
            ("经度", "str:30"),
            ("类型", "str:20"),       # 崩塌/滑坡等
            ("大小", "str:20"),       # 小型/中型等
        ],
        "source": "planned/geological_hazard_points.geojson",
        "internal_layer": "facility_point",
        "category": "planned",
        "description": "地质灾害点",
    },

    "planned_annotation": {
        "gdb_name_template": "{prefix}_注记_LJJ_{date}",
        "geometry": "Point",
        "fields": [
            ("注记", "str:100"),     # 注记文字
            ("分类", "str:20"),      # 注记分类 (规划设施点/地名等)
        ],
        "source": "planned/annotation.geojson",
        "internal_layer": "annotation",
        "category": "planned",
        "description": "规划注记",
    },

    "planned_road": {
        "gdb_name_template": "{prefix}_农村居民点外道路_LJJ_{date}",
        "geometry": "MultiLineString",
        "fields": [
            ("LnType", "float64"),
            ("LeftLn_FID", "float64"),
            ("RightLn_FID", "float64"),
            ("F1", "float64"),
            ("Shape_Length", "float64"),
        ],
        "source": "planned/road.geojson",
        "internal_layer": "infrastructure",
        "category": "planned",
        "description": "规划道路",
    },
}


# ============================================
# Internal LayerType → GDB layer mapping
# ============================================

# One internal LayerType may map to multiple GDB layers
# (e.g. boundary → admin_area + admin_boundary_line)
INTERNAL_LAYER_TO_GDB_KEYS: Dict[str, List[str]] = {
    "boundary": ["admin_area", "admin_boundary_line"],
    "function_zone": ["current_landuse", "planned_landuse"],
    "infrastructure": ["current_road", "planned_road"],
    "ecological_redline": ["ecological_redline"],
    "farmland_protection": ["farmland_protection"],
    "historical_protection": ["historical_protection"],
    "construction_zone": ["construction_zone"],
    "space_control_zone": ["space_control_zone"],
    "land_use_zone": ["land_use_zone"],
    "facility_point": ["hazard_points"],
    "annotation": ["current_annotation", "planned_annotation"],
    # No GDB mapping for these internal-only layers
    "planning_zone": [],
    "sensitivity_zone": [],      # deprecated aggregate
    "development_axis": [],      # rendering only
    "settlement_zone": [],       # rendering only, DXF "房屋" layer
    "isochrone": [],             # analysis only
}


# ============================================
# GDB field type → Python type mapping
# ============================================

GDB_DTYPE_TO_PYTHON = {
    "int16": "Int16",      # nullable int16
    "int32": "Int32",      # nullable int32
    "float32": "float32",
    "float64": "float64",
    "str:4": "str",
    "str:10": "str",
    "str:12": "str",
    "str:18": "str",
    "str:20": "str",
    "str:30": "str",
    "str:50": "str",
    "str:100": "str",
    "str:255": "str",
}


def get_gdb_layer_names(
    prefix: str = DEFAULT_GDB_PREFIX,
    date: str = DEFAULT_GDB_DATE,
) -> Dict[str, str]:
    """Get all GDB layer names with prefix and date substituted.

    Returns: {gdb_key: resolved_gdb_name}
    """
    result = {}
    for key, defn in GDB_LAYER_REGISTRY.items():
        template = defn["gdb_name_template"]
        result[key] = template.format(prefix=prefix, date=date)
    return result


def get_gdb_fields(gdb_key: str) -> List[GdbFieldSpec]:
    """Get field specifications for a GDB layer key."""
    defn = GDB_LAYER_REGISTRY.get(gdb_key)
    if not defn:
        return []
    return defn["fields"]


def get_internal_layer_for_gdb_key(gdb_key: str) -> Optional[str]:
    """Get the internal LayerType for a GDB layer key."""
    defn = GDB_LAYER_REGISTRY.get(gdb_key)
    if not defn:
        return None
    return defn.get("internal_layer")


def get_gdb_keys_for_internal_layer(internal_layer: str) -> List[str]:
    """Get all GDB layer keys that map to an internal LayerType."""
    return INTERNAL_LAYER_TO_GDB_KEYS.get(internal_layer, [])


def get_gdb_layers_by_category(category: str) -> Dict[str, LayerDef]:
    """Get all GDB layer definitions for a category ('current' or 'planned')."""
    return {
        k: v for k, v in GDB_LAYER_REGISTRY.items()
        if v.get("category") == category
    }


# ============================================
# GeoJSON → GDB field enrichment
# ============================================

def enrich_gdb_fields(
    geojson: Dict[str, Any],
    gdb_key: str,
    xzqhdm: str = "",
    xzqhmc: str = "",
) -> Dict[str, Any]:
    """Enrich GeoJSON features with GDB-required attribute fields.

    For each feature, adds missing GDB fields with sensible defaults.
    Existing properties are preserved — only missing fields are filled.

    Args:
        geojson: FeatureCollection dict to enrich
        gdb_key: Key in GDB_LAYER_REGISTRY (e.g. "current_landuse")
        xzqhdm: Administrative division code (e.g. "441426108004")
        xzqhmc: Administrative division name (e.g. "金田村")

    Returns:
        The same geojson dict with enriched feature properties
    """
    if not geojson or not geojson.get("features"):
        return geojson

    defn = GDB_LAYER_REGISTRY.get(gdb_key)
    if not defn:
        return geojson

    required_fields = defn["fields"]
    category = defn.get("category", "current")

    for feat in geojson["features"]:
        props = feat.setdefault("properties", {})

        for field_name, field_type in required_fields:
            if field_name in props and props[field_name] is not None:
                continue  # already present

            # Generate sensible defaults based on field name and type
            if field_name == "BSM":
                props[field_name] = ""  # filled later by BSM generator
            elif field_name == "YSDM":
                props[field_name] = _default_ysdm(gdb_key)
            elif field_name == "DJZQMC":
                props[field_name] = xzqhmc
            elif field_name == "DJZQDM":
                props[field_name] = xzqhdm
            elif field_name == "XZQHDM":
                props[field_name] = xzqhdm
            elif field_name in ("XZQHMC", "XZQHM"):
                props[field_name] = xzqhmc
            elif field_name == "LX":
                props[field_name] = "有条件建设区"
            elif field_name == "GHYTMC":
                # Try to derive from existing DLBM or zone_type
                from . import get_zone_type_for_ghytbm, GHYTMC_TO_ZONE_TYPE
                ghytbm = props.get("GHYTBM", "")
                if ghytbm:
                    from . import get_ghytmc_for_ghytbm
                    props[field_name] = get_ghytmc_for_ghytbm(ghytbm)
                else:
                    props[field_name] = ""
            elif field_name == "GHYTBM":
                props[field_name] = ""
            elif field_name == "GHFLBM":
                props[field_name] = ""
            elif field_name == "QMGHFLBM":
                props[field_name] = props.get("GHFLBM", "")
            elif field_name == "QMDLBM":
                props[field_name] = props.get("DLBM", "")
            elif field_name == "DLMC":
                dlbm = props.get("DLBM", "")
                if dlbm:
                    from . import DLBM_TO_DLMC
                    props[field_name] = DLBM_TO_DLMC.get(dlbm, "")
                else:
                    props[field_name] = ""
            elif field_name == "SDDLBM":
                props[field_name] = str(props.get("DLBM", "")).strip()
            elif field_name == "SDDLMC":
                props[field_name] = str(props.get("DLMC", "")).strip()
            elif field_name in ("MJ", "DLMJ", "JBNT_MJ"):
                # Will be computed from geometry later
                props[field_name] = 0.0
            elif field_name == "MS":
                props[field_name] = "无"
            elif field_name == "TBH":
                props[field_name] = ""
            elif field_name == "BH":
                props[field_name] = ""
            elif field_name == "LYYSDM":
                props[field_name] = ""
            elif field_name in ("BZ", "分类"):
                props[field_name] = ""
            elif field_name == "注记":
                props[field_name] = ""
            elif field_name.startswith("Shape_") or field_name.startswith("SHAPE_"):
                pass  # computed from geometry by GIS engine
            elif field_type.startswith("float"):
                props[field_name] = 0.0
            elif field_type.startswith("int"):
                props[field_name] = 0
            else:
                props[field_name] = ""

    return geojson


def _default_ysdm(gdb_key: str) -> str:
    """Return default YSDM (要素代码) for a GDB layer key.

    YSDM follows GB/T standards:
      - 1000600800 for administrative boundaries
      - 2001010100 for land use parcels
      - 2003020100 for farmland protection
    """
    YSDM_DEFAULTS = {
        "admin_area": "1000600800",
        "admin_boundary_line": "1000600800",
        "current_landuse": "2001010100",
        "planned_landuse": "2003070100",
        "ecological_redline": "2003020100",
        "farmland_protection": "2003020100",
        "historical_protection": "2003020100",
        "construction_zone": "2001010100",
    }
    return YSDM_DEFAULTS.get(gdb_key, "2001010100")


__all__ = [
    "FEATURE_TYPE_CODES",
    "DEFAULT_GDB_PREFIX",
    "DEFAULT_GDB_DATE",
    "GDB_LAYER_REGISTRY",
    "INTERNAL_LAYER_TO_GDB_KEYS",
    "GDB_DTYPE_TO_PYTHON",
    "GdbFieldSpec",
    "LayerDef",
    "make_gdb_layer_name",
    "get_gdb_layer_names",
    "get_gdb_fields",
    "get_internal_layer_for_gdb_key",
    "get_gdb_keys_for_internal_layer",
    "get_gdb_layers_by_category",
    "enrich_gdb_fields",
]
