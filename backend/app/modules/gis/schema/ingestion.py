"""GIS Data Ingestion Layer — 输入边界，隔绝不规范文件。

读取原始 GeoJSON → 校验字段编码体系归属 → 产出类型化对象。
所有下游代码使用 EnrichedLandUseParcel，不再直接操作 GeoJSON properties dict。

编码体系:
  gbt21010  — GB/T 21010-2017 三调国标
  tugui     — 广东省县级土地利用总体规划数据库标准
  appendix5 — 广东省技术指南附录5 村庄规划用地分类
  ghflbm    — 规划分类编码 (比appendix5更粗)
  ydyhfldm  — 自然资发〔2023〕234号 用地用海分类
  vne       — 住建部V/N/E分类

数据流:
  三调 (gbt21010) → 基数转换 → 用地用海 (ydyhfldm)
                  → 规划编制 → QMDLTB.DLBM/QMDLBM (tugui)
                            → QMDLTB.GHYTBM (appendix5)
                            → QMDLTB.GHFLBM (ghflbm)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# Encoding system constants
# ============================================================

GB_T21010 = "gbt21010"
TUGUI = "tugui"
APPENDIX5 = "appendix5"
GHFLBM_SYS = "ghflbm"
YDYHFL = "ydyhfldm"
VNE = "vne"


# ============================================================
# Field → expected encoding system mappings (per layer type)
# ============================================================

_CURRENT_LANDUSE_FIELD_SYSTEMS = {
    "DLBM": APPENDIX5,      # 现状层 GDB 实际使用附录5编码 (编制实践)
    "SDDLBM": APPENDIX5,    # 导出时从 DLBM 复制, 值同附录5
    "DLMC": None,           # 名称, 非编码
}

_PLANNED_LANDUSE_FIELD_SYSTEMS = {
    "DLBM": TUGUI,           # 基期地类编码 (土规数据库标准)
    "QMDLBM": TUGUI,         # 期末地类编码 (土规数据库标准)
    "GHYTBM": APPENDIX5,     # 规划用途编码 (附录5)
    "GHYTMC": None,          # 名称, 非编码
    "GHFLBM": GHFLBM_SYS,    # 规划分类编码
    "QMGHFLBM": GHFLBM_SYS,  # 期末规划分类编码
}

# Layers: internal_key → (field_systems_map, expected_encoding_for_DLBM)
_LAYER_META = {
    "current_landuse": (_CURRENT_LANDUSE_FIELD_SYSTEMS, APPENDIX5),
    "planned_landuse": (_PLANNED_LANDUSE_FIELD_SYSTEMS, TUGUI),
}


# ============================================================
# Typed spatial features — 统一基类 + 按空间要素类别分组
# ============================================================
#
#   SpatialFeature               — 所有空间要素基类 (geometry, bsm, ysdm)
#     ├── BaseLandUseParcel      — 地块共享属性 (dlbm, name, area, zones)
#     │     ├── CurrentLandUseParcel  — 现状层 (sddlbm)
#     │     └── PlannedLandUseParcel  — 规划层 (qmdlbm, ghytbm, ghflbm)
#     ├── AdminArea              — 村级行政区 (面) → spatial_types.py
#     ├── ControlLine            — 控制线基类 → spatial_types.py
#     └── ...                    — 其他空间要素 → spatial_types.py
#
#   编码体系标记:
#     dlbm_system:   现状=appendix5, 规划=tugui
#     sddlbm_system: 现状=appendix5 (从DLBM复制)
#     qmdlbm_system: 规划=tugui
#     ghytbm_system: 规划=appendix5
#     ghflbm_system: 规划=ghflbm
# ============================================================

from typing import Union


@dataclass
class SpatialFeature:
    """所有空间要素的统一基类 — 从 GeoJSON Feature 解析。

    共享字段:
      - geometry: GeoJSON 几何对象 (必选, 无默认值)
      - bsm: 标识码 (必选, 流水编号)
      - ysdm: 要素代码 (必选, 10位)
      - _raw: 原始 properties dict (调试用, 禁止业务使用)
    """

    geometry: Dict[str, Any]      # GeoJSON geometry

    bsm: str = ""                 # 标识码 (必选, 流水编号)
    ysdm: str = ""                # 要素代码 (必选, 10位)

    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")


@dataclass
class BaseLandUseParcel(SpatialFeature):
    """地块基类 — 现状层和规划层的共享属性。

    所有下游泛型代码使用此类处理不区分层的数据。
    需要层特定字段时使用 CurrentLandUseParcel 或 PlannedLandUseParcel。
    """

    # ── 地类编码 (共享, 但编码体系因层而异) ──
    dlbm: str = ""
    dlbm_system: str = ""    # 现状=appendix5, 规划=tugui

    # ── 通用属性 ──
    name: str = ""           # DLMC/GHYTMC 等名称字段
    area_sqm: float = 0.0    # 面积 (平方米)

    # ── 计算属性 ──
    zone_type: str = ""       # 从编码查表获得 (功能分区)
    planning_zone: str = ""   # 从编码查表获得 (规划分区)
    primary_zone: str = ""    # 从编码查表获得 (三区三线)

    @property
    def primary_code(self) -> str:
        """功能分区的首选编码 (基类默认用 DLBM)."""
        return self.dlbm

    @property
    def primary_system(self) -> str:
        """primary_code 对应的编码体系."""
        return self.dlbm_system


@dataclass
class CurrentLandUseParcel(BaseLandUseParcel):
    """现状地类图斑 — DLBM 使用 appendix5 编码 (编制实践, 非规范要求).

    独有字段: sddlbm (三调地类编码, 从 DLBM 复制, 值同 appendix5).
    无规划字段: ghytbm, ghflbm, qmdlbm 等均不存在.
    """

    sddlbm: str = ""
    sddlbm_system: str = ""  # appendix5 (从 DLBM 复制)


@dataclass
class PlannedLandUseParcel(BaseLandUseParcel):
    """期末地类图斑 — 多编码体系并存.

    编码体系:
      dlbm/qmdlbm  → tugui (广东省土规数据库标准)
      ghytbm        → appendix5 (广东省技术指南附录5)
      ghflbm/qmghflbm → ghflbm (规划分类编码, 比 appendix5 更粗)
    """

    qmdlbm: str = ""
    qmdlbm_system: str = ""      # tugui

    ghytbm: str = ""
    ghytbm_system: str = ""      # appendix5

    ghytmc: str = ""

    ghflbm: str = ""
    ghflbm_system: str = ""      # ghflbm

    qmghflbm: str = ""
    qmghflbm_system: str = ""    # ghflbm

    @property
    def primary_code(self) -> str:
        """规划层优先用 GHYTBM(附录5) 做功能分区."""
        return self.ghytbm or self.dlbm

    @property
    def primary_system(self) -> str:
        """primary_code 对应的编码体系."""
        return self.ghytbm_system or self.dlbm_system


# 联合类型 — 用于同时处理两类地块的泛型代码
LandUseParcel = Union[CurrentLandUseParcel, PlannedLandUseParcel]


# ============================================================
# Encoding validator (lazy-loaded from DictionaryCenter)
# ============================================================

class _EncodingValidator:
    """校验字段值属于哪个编码体系。使用 CodeDictionary.lookup() 避免重复提取代码集。"""

    def __init__(self):
        self._dicts: Optional[Dict[str, Any]] = None  # sys_name → CodeDictionary

    def _ensure_loaded(self):
        if self._dicts is not None:
            return
        from .dicts.loader import get_center
        center = get_center()
        self._dicts = {}
        for sys_name in [GB_T21010, TUGUI, APPENDIX5, GHFLBM_SYS, YDYHFL, VNE]:
            try:
                self._dicts[sys_name] = center.encoding(sys_name)
            except Exception:
                self._dicts[sys_name] = None

    def resolve(self, code: str, expected_system: str) -> Tuple[str, str]:
        code = str(code).strip()
        if not code:
            return "", ""

        self._ensure_loaded()
        assert self._dicts is not None

        matches = []
        for sys_name, d in self._dicts.items():
            if d is not None and d.lookup(code):
                matches.append(sys_name)

        if not matches:
            return "", f"code '{code}' not found in any encoding system"

        if len(matches) == 1:
            actual = matches[0]
            if actual == expected_system:
                return actual, ""
            else:
                return actual, f"code '{code}' found in '{actual}' but expected '{expected_system}'"

        # Multiple matches — ambiguous, prefer expected_system if among matches
        if expected_system in matches:
            return expected_system, ""
        return matches[0], (
            f"code '{code}' ambiguous: found in {matches}. "
            f"Expected '{expected_system}', resolved to '{matches[0]}'"
        )


_validator = _EncodingValidator()


# ============================================================
# Ingest functions
# ============================================================

def _read_geojson(filepath: str) -> Dict[str, Any]:
    """读取 GeoJSON 文件，返回 FeatureCollection dict。"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {filepath}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"Expected FeatureCollection, got type={data.get('type')}")
    return data


def _field_system(layer_type: str, field_name: str) -> str:
    """返回某图层某字段的预期编码体系。"""
    field_map, _ = _LAYER_META.get(layer_type, ({}, ""))
    return field_map.get(field_name, "")


def _resolve_code(
    code: Any,
    field_name: str,
    layer_type: str,
    warnings: List[str],
    feature_index: int,
) -> Tuple[str, str]:
    """校验一个编码字段并返回 (value, system, warning)。

    只有明确是编码字段 (field_name 在 LAYER_META 中有定义) 才做校验。
    其他字段直接返回值，system=""。
    """
    code_str = str(code).strip() if code is not None else ""
    if not code_str:
        return "", ""

    expected = _field_system(layer_type, field_name)
    if not expected:
        return code_str, ""  # 非编码字段, 不校验

    system, warning = _validator.resolve(code_str, expected)
    if warning:
        warnings.append(f"[feature#{feature_index}] {field_name}: {warning}")

    return code_str, system


def ingest_landuse(
    filepath: str,
    layer_type: str = "current_landuse",
    strict: bool = False,
) -> Tuple[List[BaseLandUseParcel], List[str]]:
    """解析 GeoJSON 地类图层，校验编码体系, 返回类型化地块列表。

    Args:
        filepath: GeoJSON 文件路径
        layer_type: "current_landuse" | "planned_landuse"
        strict: 如果 True，编码不匹配时抛出 ValueError

    Returns:
        (parcels, warnings): 现状层返回 CurrentLandUseParcel 列表,
                             规划层返回 PlannedLandUseParcel 列表
    """
    if layer_type not in _LAYER_META:
        raise ValueError(f"Unknown layer_type: {layer_type}. Expected one of {list(_LAYER_META.keys())}")

    # Late imports to avoid circular deps (schema.__init__ imports ingestion)
    from . import get_zone_type_for_dlbm, get_zone_type_for_ghytbm, dlbm_to_planning_zone, get_primary_zone

    data = _read_geojson(filepath)
    is_current = (layer_type == "current_landuse")
    parcels: List[BaseLandUseParcel] = []
    warnings: List[str] = []

    for i, feat in enumerate(data.get("features", [])):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        # ── 解析并校验每个编码字段 ──
        dlbm, dlbm_sys = _resolve_code(props.get("DLBM", ""), "DLBM", layer_type, warnings, i)
        sddlbm, sddlbm_sys = _resolve_code(props.get("SDDLBM", ""), "SDDLBM", layer_type, warnings, i)
        qmdlbm, qmdlbm_sys = _resolve_code(props.get("QMDLBM", ""), "QMDLBM", layer_type, warnings, i)
        ghytbm, ghytbm_sys = _resolve_code(props.get("GHYTBM", ""), "GHYTBM", layer_type, warnings, i)
        ghflbm, ghflbm_sys = _resolve_code(props.get("GHFLBM", ""), "GHFLBM", layer_type, warnings, i)
        qmghflbm, qmghflbm_sys = _resolve_code(props.get("QMGHFLBM", ""), "QMGHFLBM", layer_type, warnings, i)

        # ── 名称字段 (不校验编码) ──
        ghytmc = str(props.get("GHYTMC", props.get("ghytmc", ""))).strip()

        # ── 面积 ──
        area = props.get("DLMJ", props.get("Shape_Area", props.get("SHAPE_Area", 0)))
        area_sqm = float(area) if area else 0.0

        # ── BSM/YSDM ──
        bsm = str(props.get("BSM", "")).strip()
        ysdm = str(props.get("YSDM", "")).strip()

        # ── 名称 ──
        name = (
            ghytmc
            or str(props.get("DLMC", props.get("dlmc", ""))).strip()
            or str(props.get("GHYTMC", "")).strip()
        )

        # ── 计算 zone_type / planning_zone / primary_zone ──
        # 优先用 GHYTBM 查 zone_type (appendix5 有 zone_type 映射)
        zone_type = get_zone_type_for_ghytbm(ghytbm) if ghytbm else get_zone_type_for_dlbm(dlbm) if dlbm else ""
        planning_zone = dlbm_to_planning_zone(dlbm) if dlbm else ""
        primary_zone = get_primary_zone(dlbm) if dlbm else ""

        # ── 共享字段 ──
        shared = dict(
            geometry=geom,
            dlbm=dlbm,
            dlbm_system=dlbm_sys,
            name=name,
            area_sqm=area_sqm,
            bsm=bsm,
            ysdm=ysdm,
            zone_type=zone_type,
            planning_zone=planning_zone,
            primary_zone=primary_zone,
            _raw=props,
        )

        if is_current:
            parcels.append(CurrentLandUseParcel(
                **shared,
                sddlbm=sddlbm,
                sddlbm_system=sddlbm_sys,
            ))
        else:
            parcels.append(PlannedLandUseParcel(
                **shared,
                qmdlbm=qmdlbm,
                qmdlbm_system=qmdlbm_sys,
                ghytbm=ghytbm,
                ghytbm_system=ghytbm_sys,
                ghytmc=ghytmc,
                ghflbm=ghflbm,
                ghflbm_system=ghflbm_sys,
                qmghflbm=qmghflbm,
                qmghflbm_system=qmghflbm_sys,
            ))

    # ── 汇总 ──
    unique_codes = len({p.dlbm for p in parcels if p.dlbm})
    unique_systems = len({p.dlbm_system for p in parcels if p.dlbm_system})
    logger.info(
        "[Ingestion] %s: %d parcels, %d unique DLBM codes, %d systems. Warnings: %d",
        Path(filepath).name, len(parcels), unique_codes, unique_systems, len(warnings),
    )

    if strict and warnings:
        raise ValueError(f"Encoding validation failed with {len(warnings)} warnings:\n" + "\n".join(warnings[:10]))

    return parcels, warnings


def ingest_current_landuse(filepath: str) -> Tuple[List[CurrentLandUseParcel], List[str]]:
    """解析现状地类图斑 (current/landuse.geojson)."""
    parcels, warnings = ingest_landuse(filepath, layer_type="current_landuse")
    return parcels, warnings  # type: ignore[return-value]


def ingest_planned_landuse(filepath: str) -> Tuple[List[PlannedLandUseParcel], List[str]]:
    """解析期末地类图斑 (planned/landuse.geojson)."""
    parcels, warnings = ingest_landuse(filepath, layer_type="planned_landuse")
    return parcels, warnings  # type: ignore[return-value]


def provider_to_parcel(
    pp,  # ProviderLandParcel (from canonical.py)
    layer_type: str = "current_landuse",
) -> BaseLandUseParcel:
    """将外部 API 地块 (ProviderLandParcel) 转换为管道类型。

    ProviderLandParcel 是未校验的薄 GeoFeature 包装（天地图/OSM/高德产出）。
    此函数将其转换为 BaseLandUseParcel 并通过编码校验器标注 _system 标记，
    确保外部 API 数据与 GeoJSON 输入走同一条入口校验路径。

    由于 Provider 数据没有图层上下文（无法区分现状/规划的 encoding 预设），
    默认按现状层处理（dlbm_system = appendix5），可由调用方覆盖。
    """
    from . import get_zone_type_for_dlbm, dlbm_to_planning_zone, get_primary_zone

    # 校验 DLBM 编码体系
    dlbm = pp.dlbm.strip()
    dlbm_sys = ""
    if dlbm:
        dlbm_sys, _warning = _validator.resolve(dlbm, APPENDIX5 if layer_type == "current_landuse" else TUGUI)
        # Warning silently logged; Provider data often has non-standard codes.

    # 计算分区
    zone_type = get_zone_type_for_dlbm(dlbm) if dlbm else pp.zone_type
    planning_zone = dlbm_to_planning_zone(dlbm) if dlbm else pp.planning_zone
    primary_zone = get_primary_zone(dlbm) if dlbm else pp.primary_zone

    # 提取 properties 中的 BSM/YSDM（如果有）
    props = pp.properties or {}
    bsm = str(props.get("BSM", ""))
    ysdm = str(props.get("YSDM", ""))

    return CurrentLandUseParcel(
        geometry=pp.geometry,
        dlbm=dlbm,
        dlbm_system=dlbm_sys,
        name=getattr(pp, 'name', '') or props.get("DLMC", ""),
        area_sqm=pp.area_sqm or (pp.area_ha * 10000 if pp.area_ha else 0),
        bsm=bsm,
        ysdm=ysdm,
        zone_type=zone_type,
        planning_zone=planning_zone,
        primary_zone=primary_zone,
        sddlbm="",  # Provider 没有 sddlbm
        sddlbm_system="",
        _raw=props,
    )


# ============================================================
# Generic spatial feature ingestion (non-land-use elements)
# ============================================================

# Feature type → (model class, GDB source path)
_FEATURE_TYPE_REGISTRY: Dict[str, tuple] = {}

def _init_feature_registry():
    """Lazy-init the feature type registry (avoids circular import with spatial_types)."""
    if _FEATURE_TYPE_REGISTRY:
        return
    from .spatial_types import (
        AdminArea, AdminBoundaryLine,
        CurrentBuilding, CurrentRoad, CurrentFacility, CurrentAnnotation,
        PlannedRoad, GeologicalHazardPoint, ConditionalConstructionZone,
        FarmlandProtection, EcologicalRedline, CultivatedLandTarget,
        UrbanDevBoundary, VillageDevBoundary,
        HazardControlLine, FloodControlLine, HistoricalProtection,
        LandUseZone, ConstructionCtrlZone, PlanningScope,
    )
    _FEATURE_TYPE_REGISTRY.update({
        "admin_area":            (AdminArea,             "current/boundary.geojson"),
        "admin_boundary_line":   (AdminBoundaryLine,     "current/admin_boundary_line.geojson"),
        "current_building":      (CurrentBuilding,       "current/building.geojson"),
        "current_road":          (CurrentRoad,           "current/road.geojson"),
        "current_facility":      (CurrentFacility,       "current/facility.geojson"),
        "current_annotation":    (CurrentAnnotation,     "current/annotation.geojson"),
        "planned_road":          (PlannedRoad,           "planned/road.geojson"),
        "planned_annotation":    (CurrentAnnotation,     "planned/annotation.geojson"),
        "geological_hazard_pt":  (GeologicalHazardPoint, "planned/geological_hazard_points.geojson"),
        "conditional_construction": (ConditionalConstructionZone, "planned/construction_zone.geojson"),
        "planning_scope":        (PlanningScope,         "planned/boundary.geojson"),
        "farmland_protection":   (FarmlandProtection,    "planned/farmland_protection.geojson"),
        "ecological_redline":    (EcologicalRedline,     "planned/ecological_protection.geojson"),
        "cultivated_land_target": (CultivatedLandTarget, "planned/cultivated_land_target.geojson"),
        "urban_dev_boundary":    (UrbanDevBoundary,      "planned/urban_dev_boundary.geojson"),
        "village_dev_boundary":  (VillageDevBoundary,    "planned/village_dev_boundary.geojson"),
        "hazard_control_line":   (HazardControlLine,     "planned/hazard_control_line.geojson"),
        "flood_control_line":    (FloodControlLine,      "planned/flood_control_line.geojson"),
        "historical_protection": (HistoricalProtection,  "planned/historical_protection.geojson"),
        "land_use_zone":         (LandUseZone,           "planned/land_use_zone.geojson"),
        "construction_ctrl_zone": (ConstructionCtrlZone, "planned/space_control_zone.geojson"),
    })


def ingest_feature(
    filepath: str,
    feature_type: str,
) -> Tuple[List[SpatialFeature], List[str]]:
    """通用空间要素摄入 — 按 feature_type 选择对应的类型化模型。

    读取 GeoJSON FeatureCollection, 将每个 feature 的属性映射到类型化对象。

    Args:
        filepath: GeoJSON 文件路径
        feature_type: 要素类型 (见 _FEATURE_TYPE_REGISTRY 键值)

    Returns:
        (features, warnings): 类型化空间要素列表和警告信息

    支持的类型 (部分):
      admin_area, admin_boundary_line,
      current_building, current_road, current_facility, current_annotation,
      farmland_protection, ecological_redline, cultivated_land_target,
      urban_dev_boundary, village_dev_boundary,
      hazard_control_line, flood_control_line, historical_protection,
      land_use_zone, construction_ctrl_zone, planning_scope
    """
    _init_feature_registry()

    if feature_type not in _FEATURE_TYPE_REGISTRY:
        raise ValueError(
            f"Unknown feature_type: {feature_type}. "
            f"Expected one of {list(_FEATURE_TYPE_REGISTRY.keys())}"
        )

    model_cls, _default_source = _FEATURE_TYPE_REGISTRY[feature_type]
    data = _read_geojson(filepath)
    features: List[SpatialFeature] = []
    warnings: List[str] = []

    # Pre-compute field type map once per feature type (not per feature)
    import dataclasses
    _model_fields = {f.name: f.type for f in dataclasses.fields(model_cls)}

    for i, feat in enumerate(data.get("features", [])):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        kwargs: Dict[str, Any] = {"geometry": geom, "_raw": props}

        for field_name in _model_fields:
            if field_name in ("geometry", "_raw"):
                continue
            # Map common property key variants
            prop_key = field_name.upper()  # e.g. "bsm" → "BSM"
            alt_key = field_name  # e.g. "xzqhdm" → "xzqhdm"
            value = props.get(prop_key, props.get(alt_key))

            if value is not None:
                field_type = _model_fields[field_name]
                try:
                    if field_type in (int, "int"):
                        kwargs[field_name] = int(value) if value != "" else 0
                    elif field_type in (float, "float"):
                        kwargs[field_name] = float(value) if value != "" else 0.0
                    else:
                        kwargs[field_name] = str(value).strip()
                except (ValueError, TypeError):
                    kwargs[field_name] = "" if field_type is str else 0

        try:
            features.append(model_cls(**kwargs))
        except Exception as e:
            warnings.append(f"[feature#{i}] Failed to create {feature_type}: {e}")

    logger.info(
        "[Ingestion] %s: %d features ingested as %s. Warnings: %d",
        Path(filepath).name, len(features), feature_type, len(warnings),
    )
    return features, warnings


# ============================================================
# Internal debug helpers (not exported via __init__.py)
# ============================================================

def _report(parcels: List[BaseLandUseParcel]) -> str:
    """生成编码体系诊断报告 (内部调试用, 不对外导出)."""
    lines = [f"=== Encoding Report: {len(parcels)} parcels ===", ""]

    # DLBM systems
    sys_dist: Dict[str, int] = {}
    for p in parcels:
        key = p.dlbm_system or "(unknown)"
        sys_dist[key] = sys_dist.get(key, 0) + 1
    lines.append("DLBM encoding distribution:")
    for sys_name, count in sorted(sys_dist.items(), key=lambda x: -x[1]):
        lines.append(f"  {sys_name}: {count}")
    lines.append("")

    # GHYTBM systems (planned layer only)
    ghytbm_dist: Dict[str, int] = {}
    for p in parcels:
        if isinstance(p, PlannedLandUseParcel) and p.ghytbm:
            key = p.ghytbm_system or "(unknown)"
            ghytbm_dist[key] = ghytbm_dist.get(key, 0) + 1
    if ghytbm_dist:
        lines.append("GHYTBM encoding distribution:")
        for sys_name, count in sorted(ghytbm_dist.items(), key=lambda x: -x[1]):
            lines.append(f"  {sys_name}: {count}")
        lines.append("")

    # Unique codes per system
    codes_per_sys: Dict[str, Set[str]] = {}
    for p in parcels:
        if p.dlbm and p.dlbm_system:
            codes_per_sys.setdefault(p.dlbm_system, set()).add(p.dlbm)
    lines.append("Unique DLBM codes per system:")
    for sys_name, codes in sorted(codes_per_sys.items()):
        lines.append(f"  {sys_name}: {len(codes)} codes — {sorted(codes)[:10]}{'...' if len(codes) > 10 else ''}")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "SpatialFeature",
    "BaseLandUseParcel",
    "CurrentLandUseParcel",
    "PlannedLandUseParcel",
    "LandUseParcel",
    "ingest_landuse",
    "ingest_current_landuse",
    "ingest_planned_landuse",
    "ingest_feature",
    "GB_T21010",
    "TUGUI",
    "APPENDIX5",
    "GHFLBM_SYS",
    "YDYHFL",
    "VNE",
]
