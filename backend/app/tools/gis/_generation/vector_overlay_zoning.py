from typing import Iterable, Tuple, List

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.modules.kg.ontology import ThreeLineSubtypes
from app.modules.schema.provenance import ProvenanceAudit, ProvenanceSource


# Six-code 空间管制码 (广东 01-06):
#   01 允许建设区: 在 boundary 内 且 在村庄建设边界 (ZJDJSFWX) 内
#   02 限制建设区: 在 boundary 内 但 不在任何三线内
#   03 有条件建设区: 在 boundary 内 且 在城镇开发边界 (UDB) 内
#   04 禁止建设区: 在 生态保护红线 内
#   05 已有建设区: 在 永久基本农田 内 且 现状为建设用地
#   06 待置换区:   在 永久基本农田 内 且 现状为非建设用地

CONSTRUCTION_DLBM_PREFIXES: tuple[str, ...] = (
    "07",  # 住宅用地
    "08",  # 公共管理与公共服务用地
    "09",  # 特殊用地
    "10",  # 交通运输用地
    "11",  # 水域及水利设施用地 (部分)
    "12",  # 其他土地 (有建筑标注的)
)


def _merge(features: Iterable[dict]) -> BaseGeometry | None:
    geoms = [f["geometry"] for f in features if f.get("geometry") is not None]
    if not geoms:
        return None
    return unary_union(geoms)


def _classify(geom, eco, farm, udb, vcb, dlbm: str) -> str:
    if eco is not None and geom.intersects(eco):
        return "04"
    if farm is not None and geom.intersects(farm):
        if dlbm[:2] in CONSTRUCTION_DLBM_PREFIXES:
            return "05"
        return "06"
    if udb is not None and geom.intersects(udb):
        return "03"
    if vcb is not None and geom.intersects(vcb):
        return "01"
    return "02"


def compute_control_codes(
    parcels: Iterable[dict],
    three_lines: dict,
    boundary: BaseGeometry,
    *,
    bsm_key: str = "bsm",
    geom_key: str = "geometry",
    dlbm_key: str = "dlbm",
) -> Tuple[dict[str, str], ProvenanceAudit]:
    """Assign 6-码 control_code to each parcel based on three-line spatial containment.

    Args:
        parcels: iterable of dicts with bsm/geometry/dlbm
        three_lines: dict keyed by ThreeLineSubtypes values → feature list
        boundary: village boundary geometry (parcels outside are excluded from layer)

    Returns:
        (code_map, audit) — code_map is {bsm: code}, audit records missing lines.
    """
    audit = ProvenanceAudit()
    eco = _merge(three_lines.get(ThreeLineSubtypes.ECOLOGICAL_REDLINE, []))
    farm = _merge(three_lines.get(ThreeLineSubtypes.FARMLAND_REDLINE, []))
    udb = _merge(three_lines.get(ThreeLineSubtypes.URBAN_DEV_BOUNDARY, []))
    vcb = _merge(three_lines.get(ThreeLineSubtypes.VILLAGE_CONSTRUCTION_BOUNDARY, []))

    if eco is None:
        audit.record("three_line.ecological_redline", ProvenanceSource.MISSING_THREE_LINE, parcel_count=0)
    if farm is None:
        audit.record("three_line.farmland_redline", ProvenanceSource.MISSING_THREE_LINE, parcel_count=0)
    if udb is None:
        audit.record("three_line.urban_dev_boundary", ProvenanceSource.MISSING_URBAN_DEV_BOUNDARY, parcel_count=0)
    if vcb is None:
        audit.record("three_line.village_construction_boundary", ProvenanceSource.MISSING_THREE_LINE, parcel_count=0)

    code_map: dict[str, str] = {}
    for p in parcels:
        geom = p.get(geom_key)
        bsm = p.get(bsm_key)
        if geom is None or bsm is None:
            continue
        if not geom.intersects(boundary):
            continue
        code_map[bsm] = _classify(geom, eco, farm, udb, vcb, str(p.get(dlbm_key, "")))

    audit.record("control_zone", ProvenanceSource.DERIVED_THREE_LINE_OVERLAY, parcel_count=len(code_map))
    return code_map, audit


def compute_planning_zones(
    parcels: Iterable[dict],
    upper_plan_zones: dict,
    *,
    bsm_key: str = "bsm",
    geom_key: str = "geometry",
) -> Tuple[dict[str, str], ProvenanceAudit]:
    """Assign 6-类 planning_zone via spatial containment within upper-level 土规.

    Args:
        parcels: iterable of dicts with bsm/geometry
        upper_plan_zones: ``{zone_name: [feature_dict, ...]}`` from
            ``gd_planning_zones`` (县级土规传导矢量). Missing → audit only.

    Returns:
        (zone_map, audit) — zone_map is {bsm: zone_name}, audit records missing
        upper plan.
    """
    audit = ProvenanceAudit()
    if not upper_plan_zones:
        audit.record("planning_zone", ProvenanceSource.MISSING_UPPER_PLAN, parcel_count=0)
        return {}, audit

    zone_map: dict[str, str] = {}
    for zone_name, features in upper_plan_zones.items():
        merged = _merge(features or [])
        if merged is None:
            continue
        for p in parcels:
            geom = p.get(geom_key)
            bsm = p.get(bsm_key)
            if geom is None or bsm is None:
                continue
            if bsm in zone_map:
                continue
            if geom.intersects(merged):
                zone_map[bsm] = zone_name

    audit.record(
        "planning_zone",
        ProvenanceSource.DERIVED_UPPER_PLAN_OVERLAY if zone_map else ProvenanceSource.MISSING_UPPER_PLAN,
        parcel_count=len(zone_map),
    )
    return zone_map, audit