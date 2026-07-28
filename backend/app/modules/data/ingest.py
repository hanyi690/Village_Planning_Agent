"""Data ingestion port - raw GeoJSON / GeoTIFF -> typed schema models.

This is the ONLY place where raw file/API data is validated and converted
into typed spatial models. All other layers (kg / parse / gis tools) MUST
consume the typed models from `app.modules.schema`, never raw dicts.

Migrated from `app/modules/gis/schema/ingestion.py` - ingestion is a
data-layer concern (it reads data and validates it), so it lives here next
to the drivers that produce raw GeoJSON. The type definitions stay in
`modules/schema/types/spatial_types.py` (schema layer = pure definitions).

Pipeline:
    DataCatalog.fetch() -> DataResult(raw geojson)
                              |
                              v
                        ingest.result_to_parcels() / result_to_features()
                              |  (encoding validation + typing)
                              v
                        schema models (BaseLandUseParcel, SpatialFeature, ...)
                              |
                              v
                        kg / parse / gis tools (consume typed models)

Encoding systems:
  gbt21010  - GB/T 21010-2017 三调国标
  tugui     - 广东省县级土地利用总体规划数据库标准
  appendix5 - 广东省技术指南附录5 村庄规划用地分类
  ghflbm    - 规划分类编码 (比appendix5更粗)
  ydyhfldm  - 自然资发〔2023〕234号 用地用海分类
  vne       - 住建部V/N/E分类

Data flow:
  三调 (gbt21010) -> 基数转换 -> 用地用海 (ydyhfldm)
                  -> 规划编制 -> QMDLTB.DLBM/QMDLBM (tugui)
                            -> QMDLTB.GHYTBM (appendix5)
                            -> QMDLTB.GHFLBM (ghflbm)
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.modules.schema.types.spatial_types import (
    SpatialFeature,
    BaseLandUseParcel,
    CurrentLandUseParcel,
    PlannedLandUseParcel,
    GB_T21010,
    TUGUI,
    APPENDIX5,
    GHFLBM_SYS,
    YDYHFL,
    VNE,
)
from app.utils.logger import get_logger

from .contracts import DataResult

logger = get_logger(__name__)


# ============================================================
# Field -> expected encoding system mappings (per layer type)
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

# Layers: internal_key -> (field_systems_map, expected_encoding_for_DLBM)
_LAYER_META = {
    "current_landuse": (_CURRENT_LANDUSE_FIELD_SYSTEMS, APPENDIX5),
    "planned_landuse": (_PLANNED_LANDUSE_FIELD_SYSTEMS, TUGUI),
}


# ============================================================
# Encoding validator (lazy-loaded from DictionaryCenter)
# ============================================================

class _EncodingValidator:
    """校验字段值属于哪个编码体系。使用 CodeDictionary.lookup() 避免重复提取代码集。"""

    def __init__(self):
        self._dicts: Optional[Dict[str, Any]] = None  # sys_name -> CodeDictionary

    def _ensure_loaded(self):
        if self._dicts is not None:
            return
        from app.modules.schema.encodings.dicts.loader import get_center
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

        # Multiple matches - ambiguous, prefer expected_system if among matches
        if expected_system in matches:
            return expected_system, ""
        return matches[0], (
            f"code '{code}' ambiguous: found in {matches}. "
            f"Expected '{expected_system}', resolved to '{matches[0]}'"
        )


_validator = _EncodingValidator()


# ============================================================
# GeoJSON reading helpers
# ============================================================

def _read_geojson(filepath) -> Dict[str, Any]:
    """读取 GeoJSON，返回 FeatureCollection dict。

    Args:
        filepath: 文件路径 (str/Path) 或已解析的 GeoJSON dict / Feature 列表。
    """
    if isinstance(filepath, dict):
        if filepath.get("type") != "FeatureCollection":
            raise ValueError(f"Expected FeatureCollection, got type={filepath.get('type')}")
        return filepath
    if isinstance(filepath, list):
        return {"type": "FeatureCollection", "features": filepath}

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {filepath}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"Expected FeatureCollection, got type={data.get('type')}")
    return data


def _geojson_from_result(result: DataResult) -> Optional[Dict[str, Any]]:
    """Extract a GeoJSON FeatureCollection from a DataResult.

    Accepts either a FeatureCollection dict or a Feature list. Returns None
    and logs a warning if the result is not usable.
    """
    if not result.success or result.data is None:
        logger.warning("[Ingest] DataResult not successful: %s", result.error)
        return None

    data = result.data
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data
    if isinstance(data, list):
        # Bare feature list -> wrap
        return {"type": "FeatureCollection", "features": data}
    logger.warning("[Ingest] DataResult.data is not GeoJSON: type=%s", type(data).__name__)
    return None


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


# ============================================================
# Ingest functions (filepath -> typed models)
# ============================================================

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

    # Late imports to avoid triggering schema package __init__ cycles at import time
    from app.modules.schema import (
        get_zone_type_for_dlbm,
        get_zone_type_for_ghytbm,
        dlbm_to_planning_zone,
        get_primary_zone,
    )

    data = _read_geojson(filepath)
    is_current = (layer_type == "current_landuse")
    parcels: List[BaseLandUseParcel] = []
    warnings: List[str] = []

    # ── 第一遍：统计 BSM 频率，重复 BSM 追加 _seq 保证唯一 ──
    features = data.get("features", [])
    bsm_counts = {}
    for feat in features:
        bsm = str(feat.get("properties", {}).get("BSM", "")).strip()
        bsm_counts[bsm] = bsm_counts.get(bsm, 0) + 1
    bsm_seen = {}

    for i, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        # ── 解析并校验每个编码字段 ──
        dlbm, dlbm_sys = _resolve_code(props.get("DLBM", ""), "DLBM", layer_type, warnings, i)
        sddlbm, sddlbm_sys = _resolve_code(props.get("SDDLBM", ""), "SDDLBM", layer_type, warnings, i)
        qmdlbm, qmdlbm_sys = _resolve_code(props.get("QMDLBM", ""), "QMDLBM", layer_type, warnings, i)
        ghytbm, ghytbm_sys = _resolve_code(props.get("GHYTBM", ""), "GHYTBM", layer_type, warnings, i)
        ghflbm, ghflbm_sys = _resolve_code(props.get("GHFLBM", ""), "GHFLBM", layer_type, warnings, i)
        qmghflbm, qmghflbm_system = _resolve_code(props.get("QMGHFLBM", ""), "QMGHFLBM", layer_type, warnings, i)

        # ── 名称字段 (不校验编码) ──
        ghytmc = str(props.get("GHYTMC", props.get("ghytmc", ""))).strip()

        # ── 面积 ──
        area = props.get("DLMJ", props.get("Shape_Area", props.get("SHAPE_Area", 0)))
        area_sqm = float(area) if area else 0.0

        # ── BSM/YSDM ──
        bsm = str(props.get("BSM", "")).strip()
        ysdm = str(props.get("YSDM", "")).strip()

        # BSM 去重：重复 BSM 追加 _seq（首个保留原值，后续 _1, _2, ...）
        if bsm and bsm_counts.get(bsm, 0) > 1:
            seq = bsm_seen.get(bsm, 0)
            bsm_seen[bsm] = seq + 1
            if seq > 0:
                bsm = f"{bsm}_{seq}"

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
        )

        extra_props = {k: v for k, v in props.items() if k.upper() not in ('BSM', 'YSDM', 'DLBM', 'DLMC', 'DLMJ', 'SHAPE_AREA', 'SHAPE_LENGTH') and k.lower() not in ('geometry',)}

        if is_current:
            parcels.append(CurrentLandUseParcel(
                **shared,
                **extra_props,
                sddlbm=sddlbm,
                sddlbm_system=sddlbm_sys,
            ))
        else:
            parcels.append(PlannedLandUseParcel(
                **shared,
                **extra_props,
                qmdlbm=qmdlbm,
                qmdlbm_system=qmdlbm_sys,
                ghytbm=ghytbm,
                ghytbm_system=ghytbm_sys,
                ghytmc=ghytmc,
                ghflbm=ghflbm,
                ghflbm_system=ghflbm_sys,
                qmghflbm=qmghflbm,
                qmghflbm_system=qmghflbm_system,
            ))

    # ── 汇总 ──
    unique_codes = len({p.dlbm for p in parcels if p.dlbm})
    unique_systems = len({p.dlbm_system for p in parcels if p.dlbm_system})
    src_name = Path(filepath).name if isinstance(filepath, (str, Path)) else "<dict>"
    logger.info(
        "[Ingest] %s: %d parcels, %d unique DLBM codes, %d systems. Warnings: %d",
        src_name, len(parcels), unique_codes, unique_systems, len(warnings),
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


@dataclass
class _ProviderParcel:
    """Minimal provider parcel — replaces deleted ProviderLandParcel."""
    geometry: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    dlbm: str = ""
    area_ha: float = 0.0
    area_sqm: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""
    primary_zone: str = ""


def provider_to_parcel(
    pp: _ProviderParcel,
    layer_type: str = "current_landuse",
) -> BaseLandUseParcel:
    """将外部 API 地块转换为管道类型。

    接收 _ProviderParcel (替代已删除的 ProviderLandParcel/GeoFeature)，
    转换为 BaseLandUseParcel 并通过编码校验器标注 _system 标记，
    确保外部 API 数据与 GeoJSON 输入走同一条入口校验路径。

    由于 Provider 数据没有图层上下文（无法区分现状/规划的 encoding 预设），
    默认按现状层处理（dlbm_system = appendix5），可由调用方覆盖。
    """
    from app.modules.schema import (
        get_zone_type_for_dlbm,
        dlbm_to_planning_zone,
        get_primary_zone,
    )

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
        sddlbm="",
        sddlbm_system="",
    )


# ============================================================
# Generic spatial feature ingestion (non-land-use elements)
# ============================================================

# Feature type -> (model class, GDB source path)
# Derived from GIS_LAYER_REGISTRY (T6). Kept as backward compat.
_FEATURE_TYPE_REGISTRY: Dict[str, tuple] = {}

def _infer_model_class(layer_type: str) -> str:
    _CLASS_MAP = {
        "landuse_current": "CurrentLandUseParcel",
        "landuse_planned": "PlannedLandUseParcel",
        "water": "WaterFeature",
        "current_road": "CurrentRoad",
        "planned_road": "PlannedRoad",
        "admin_area": "AdminArea",
        "admin_boundary_line": "AdminBoundaryLine",
        "farmland_protection": "FarmlandProtection",
        "ecological_redline": "EcologicalRedline",
        "urban_dev_boundary": "UrbanDevBoundary",
        "village_dev_boundary": "VillageDevBoundary",
        "cultivated_land_target": "CultivatedLandTarget",
        "historical_protection": "HistoricalProtection",
        "conditional_construction_zone": "ConditionalConstructionZone",
        "geological_hazard_point": "GeologicalHazardPoint",
        "planning_scope": "PlanningScope",
        "land_use_zone": "LandUseZone",
        "construction_ctrl_zone": "ConstructionCtrlZone",
        "hazard_control_line": "HazardControlLine",
        "flood_control_line": "FloodControlLine",
        "contour_line": "ContourLine",
        "elevation_point": "ElevationPoint",
        "current_building": "CurrentBuilding",
        "current_facility": "CurrentFacility",
        "planned_facility": "PlannedFacility",
        "current_annotation": "CurrentAnnotation",
        "planned_annotation": "PlannedAnnotation",
        "three_zone_item": "ThreeZoneItem",
        "soil_type": "SoilType",
        "soil_erosion": "SoilErosion",
        "watershed": "Watershed",
        "nature_reserve": "NatureReserve",
        "hydrogeology_zone": "HydrogeologyZone",
        "dem": "DEMInput",
        "dom": "DOMInput",
        "population": "PopulationTable",
        "construction_projects": "ConstructionProjectTable",
        "control_rules": "ControlRuleTable",
        "planning_indicators": "PlanningIndicatorTable",
        "land_use_structure": "LandUseStructureTable",
    }
    return _CLASS_MAP.get(layer_type, "")


def _init_feature_registry():
    if _FEATURE_TYPE_REGISTRY:
        return
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
    from app.modules.schema import spatial_types as _st
    for lt, entry in GIS_LAYER_REGISTRY.items():
        if entry.ingest is None:
            continue
        model_class = getattr(_st, _infer_model_class(lt), None)
        if model_class is None:
            continue
        key = entry.ingest.feature_type or lt
        _FEATURE_TYPE_REGISTRY[key] = (model_class, entry.default_gdb_path)


def ingest_feature(
    filepath: str,
    feature_type: str,
) -> Tuple[List[SpatialFeature], List[str]]:
    """通用空间要素摄入 - 按 feature_type 选择对应的类型化模型。

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

    _model_fields = set(model_cls.model_fields.keys())

    for i, feat in enumerate(data.get("features", [])):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        kwargs: Dict[str, Any] = {"geometry": geom}

        for field_name in _model_fields:
            if field_name in ("geometry",):
                continue
            prop_key = field_name.upper()
            alt_key = field_name
            value = props.get(prop_key, props.get(alt_key))

            if value is not None:
                field_info = model_cls.model_fields[field_name]
                field_type = field_info.annotation if hasattr(field_info, 'annotation') else str
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

    src_name = Path(filepath).name if isinstance(filepath, (str, Path)) else "<dict>"
    logger.info(
        "[Ingest] %s: %d features ingested as %s. Warnings: %d",
        src_name, len(features), feature_type, len(warnings),
    )
    return features, warnings


# ============================================================
# Raster ingestion (DEM/DOM - metadata only, no data loading)
# ============================================================

def ingest_raster(filepath: str, raster_type: str = "dem"):
    """加载栅格元数据 (不加载栅格数据本身，仅读取元信息).

    Args:
        filepath: GeoTIFF 文件路径
        raster_type: "dem" | "dom"

    Returns:
        类型化的栅格输入对象 (DEMInput 或 DOMInput)

    Raises:
        FileNotFoundError: 文件不存在
        ImportError: rasterio 未安装
    """
    from app.modules.schema.types.raster_types import RasterDataset, DEMInput, DOMInput

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Raster file not found: {filepath}")

    try:
        import rasterio
    except ImportError:
        logger.warning("[Ingest] rasterio not installed, returning minimal RasterDataset")
        if raster_type == "dem":
            return DEMInput(path=filepath)
        elif raster_type == "dom":
            return DOMInput(path=filepath)
        else:
            return RasterDataset(path=filepath)

    with rasterio.open(filepath) as src:
        meta = dict(src.meta) if src.meta else {}
        crs = str(src.crs) if src.crs else "unknown"
        resolution = abs(src.transform[0]) if src.transform else 0.0
        nodata = src.nodata

    if raster_type == "dem":
        return DEMInput(
            path=filepath, crs=crs, resolution=resolution,
            nodata=nodata, _meta=meta,
        )
    elif raster_type == "dom":
        return DOMInput(
            path=filepath, crs=crs, resolution=resolution,
            nodata=nodata, _meta=meta,
        )
    else:
        return RasterDataset(
            path=filepath, crs=crs, resolution=resolution,
            nodata=nodata, _meta=meta,
        )


# ============================================================
# DataResult -> typed model ports (data layer -> schema models)
# ============================================================

def result_to_parcels(
    result: DataResult,
    layer_type: str = "current_landuse",
    strict: bool = False,
) -> Tuple[List[BaseLandUseParcel], List[str]]:
    """Convert a DataResult (geojson) to typed parcels via encoding validation.

    This is the bridge from the data layer (raw GeoJSON) to the schema layer
    (typed models). Writes the GeoJSON to a temp file and reuses the filepath-
    based ingest_landuse() so validation logic is not duplicated.

    Args:
        result: DataResult from a file_vector / api_vector driver fetch.
        layer_type: "current_landuse" | "planned_landuse"
        strict: raise on encoding mismatch if True

    Returns:
        (parcels, warnings)
    """
    geojson = _geojson_from_result(result)
    if geojson is None:
        return [], [result.error or "no geojson data"]

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".geojson", delete=False, encoding="utf-8"
    )
    try:
        json.dump(geojson, tmp, ensure_ascii=False)
        tmp.close()
        return ingest_landuse(tmp.name, layer_type=layer_type, strict=strict)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def result_to_features(
    result: DataResult,
    feature_type: str,
) -> Tuple[List[SpatialFeature], List[str]]:
    """Convert a DataResult (geojson) to typed spatial features.

    Args:
        result: DataResult from a file_vector / api_vector driver fetch.
        feature_type: registry key (e.g. "current_annotation", "current_road")

    Returns:
        (features, warnings)
    """
    geojson = _geojson_from_result(result)
    if geojson is None:
        return [], [result.error or "no geojson data"]

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".geojson", delete=False, encoding="utf-8"
    )
    try:
        json.dump(geojson, tmp, ensure_ascii=False)
        tmp.close()
        return ingest_feature(tmp.name, feature_type)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def result_to_raster(result: DataResult, raster_type: str = "dem"):
    """Convert a DataResult (raster path) to a typed RasterDataset.

    Expects result.data to be a file path string (local_raster driver) or
    result.cache_path for cached downloads.
    """
    path = result.data if isinstance(result.data, str) else result.cache_path
    if not path:
        return None
    return ingest_raster(path, raster_type=raster_type)


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
        lines.append(f"  {sys_name}: {len(codes)} codes - {sorted(codes)[:10]}{'...' if len(codes) > 10 else ''}")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    # Filepath-based ingest (legacy + direct use)
    "ingest_landuse",
    "ingest_current_landuse",
    "ingest_planned_landuse",
    "ingest_feature",
    "ingest_raster",
    "provider_to_parcel",
    # DataResult -> typed model ports (data layer bridge)
    "result_to_parcels",
    "result_to_features",
    "result_to_raster",
]
