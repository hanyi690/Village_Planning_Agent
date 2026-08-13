"""Stage 2.6: 定位规划实体并构建路径规划节点。
该阶段将基于证据的第二阶段文本输出转化为可解释的地理信息系统（GIS）对象。
它有意在生成新的道路几何形状之前停止：第四阶段仍负责候选路线的生成，而本模块则为后续步骤准备更清晰的节点和结构化请求。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, MultiPoint, Point, box, mapping, shape
from shapely.ops import nearest_points, transform as transform_geometry, unary_union

from .schemas import PlanningNodeBuildConfig, PlanningNodeBuildResult


SCHEMA_VERSION = "1.0"
NAME_FIELDS = ("name", "NAME", "名称", "注记", "label", "text", "place_name")
BSM_FIELDS = (
    "bsm",
    "BSM",
    "source_bsm",
    "source_bsms",
    "candidate_bsm",
    "candidate_bsms",
    "path_bsm",
    "path_bsms",
    "parcel_bsm",
    "road_bsm",
)
ROAD_ACTIONS = {
    "new": ("新建", "新增", "连通", "连接", "接入", "打通", "贯通", "至", "通往"),
    "widen": ("拓宽", "扩宽", "加宽"),
    "harden": ("硬化", "黑化", "铺装"),
    "repair": ("修复", "修缮", "整治", "提升", "改造", "完善"),
}
ROAD_ACTION_KEYWORDS = {
    "new": (
        "\u65b0\u5efa",
        "\u65b0\u589e",
        "\u8fde\u63a5",
        "\u8fde\u901a",
        "\u63a5\u5165",
        "\u6253\u901a",
        "\u8d2f\u901a",
        "\u901a\u5f80",
        "\u901a\u8fbe",
        "\u81f3",
    ),
    "widen": ("\u62d3\u5bbd", "\u6269\u5bbd", "\u52a0\u5bbd"),
    "harden": ("\u786c\u5316", "\u9ed1\u5316", "\u94fa\u88c5"),
    "repair": (
        "\u4fee\u590d",
        "\u4fee\u7f2e",
        "\u6574\u6cbb",
        "\u63d0\u5347",
        "\u6539\u9020",
        "\u5b8c\u5584",
        "\u6539\u5584",
    ),
}
ROAD_NOUN_PATTERN = (
    r"(?:\u9053\u8def|\u6751\u9053|\u516c\u8def|\u8def\u7f51|\u673a\u8015\u8def|\u751f\u4ea7\u8def|\u6d88\u9632\u901a\u9053)"
)
REQUEST_BY_ACTION = {
    "new": "new_connection",
    "widen": "road_widening",
    "harden": "road_hardening",
    "repair": "road_repair",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _feature_collection(name: str, crs: str, features: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": name,
        "schema_version": SCHEMA_VERSION,
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": list(features),
    }


def _collection_crs(payload: Mapping[str, Any], default: str) -> str:
    return str(((payload.get("crs") or {}).get("properties") or {}).get("name") or default)


def _transformer(source_crs: str, target_crs: str) -> Optional[Transformer]:
    if source_crs.upper() == target_crs.upper():
        return None
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def _transform(geometry: Any, transformer: Optional[Transformer]) -> Any:
    return geometry if transformer is None else transform_geometry(transformer.transform, geometry)


def _normalise_name(value: Any) -> str:
    return re.sub(r"[\s_（）()、，,。；;:：\-—]+", "", str(value or "")).lower()


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> List[str]:
    return [str(item) for item in _as_list(value) if str(item or "").strip()]


def _flatten_string_list(value: Any) -> List[str]:
    values: List[str] = []
    for item in _as_list(value):
        if isinstance(item, (list, tuple, set)):
            values.extend(_flatten_string_list(list(item)))
        elif str(item or "").strip():
            values.append(str(item))
    return values


def _intent_role_list(value: Any) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for item in _as_list(value):
        if not isinstance(item, Mapping):
            continue
        intent_id = str(item.get("intent_id") or "")
        role = str(item.get("role") or "")
        if not intent_id or not role:
            continue
        key = (intent_id, role)
        if key in seen:
            continue
        seen.add(key)
        records.append({"intent_id": intent_id, "role": role})
    return records


def _bbox_list(value: Any) -> Optional[List[float]]:
    raw = value
    if isinstance(value, Mapping):
        raw = value.get("bbox") or value.get("bounds")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        minx, miny, maxx, maxy = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    if minx >= maxx or miny >= maxy:
        return None
    return [minx, miny, maxx, maxy]


def _safe_jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _evidence_text(value: Mapping[str, Any]) -> str:
    evidence = value.get("evidence") or {}
    candidates = (
        value.get("evidence_text"),
        value.get("source_text"),
        evidence.get("text") if isinstance(evidence, Mapping) else None,
        evidence.get("evidence_text") if isinstance(evidence, Mapping) else None,
        evidence.get("source_text") if isinstance(evidence, Mapping) else None,
        evidence.get("raw_text") if isinstance(evidence, Mapping) else None,
    )
    return next((str(item) for item in candidates if str(item or "").strip()), "")


def _source_chunk_id(value: Mapping[str, Any]) -> Optional[str]:
    evidence = value.get("evidence") or {}
    candidates = (
        value.get("source_chunk_id"),
        value.get("chunk_id"),
        evidence.get("chunk_id") if isinstance(evidence, Mapping) else None,
        evidence.get("source_chunk_id") if isinstance(evidence, Mapping) else None,
        evidence.get("evidence_id") if isinstance(evidence, Mapping) else None,
    )
    found = next((str(item) for item in candidates if str(item or "").strip()), None)
    return found


def _source_page(value: Mapping[str, Any]) -> Optional[Any]:
    evidence = value.get("evidence") or {}
    if isinstance(evidence, Mapping):
        return evidence.get("source_page") or evidence.get("page")
    return value.get("source_page")


def _section_title(value: Mapping[str, Any]) -> Optional[str]:
    evidence = value.get("evidence") or {}
    if isinstance(evidence, Mapping):
        found = evidence.get("section_title") or evidence.get("section")
        if found:
            return str(found)
    found = value.get("section_title") or value.get("section")
    return str(found) if found else None


def _action_from_text(text: str, fallback: Any = None) -> str:
    fallback_text = str(fallback or "").lower()
    for action in REQUEST_BY_ACTION:
        if fallback_text == action:
            return action
    for action, keywords in ROAD_ACTION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return action
    for action, keywords in ROAD_ACTIONS.items():
        if any(keyword in text for keyword in keywords):
            return action
    return "new" if "至" in text or "连" in text else "repair"


def _task_type(action: str) -> str:
    if action == "new":
        return "road_connection"
    if action in {"widen", "harden", "repair"}:
        return "road_upgrade"
    return "road_planning"


def _has_road_action_text(text: str) -> bool:
    return any(keyword in text for words in ROAD_ACTION_KEYWORDS.values() for keyword in words) or any(
        keyword in text for words in ROAD_ACTIONS.values() for keyword in words
    )


def _clean_extracted_place(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"^(?:\u89c4\u5212|\u65b0\u5efa|\u65b0\u589e|\u63a8\u8fdb|\u5b9e\u65bd|\u5b8c\u5584|\u63d0\u5347|\u6539\u9020|\u6253\u901a|\u8fde\u901a|\u8fde\u63a5|\u63a5\u5165)+",
        "",
        text,
    )
    text = re.sub(ROAD_NOUN_PATTERN + r"$", "", text)
    return text.strip(" \t\r\n,，.。;；:：、（）()[]【】")


def _priority(value: Mapping[str, Any], default: str = "medium") -> str:
    raw = str(value.get("priority") or value.get("importance") or default).lower()
    if raw in {"high", "medium", "low"}:
        return raw
    if "高" in raw or "重点" in raw:
        return "high"
    if "低" in raw:
        return "low"
    return default


def _priority_rank(priority: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(priority, 2)


def _node_type(entity_type: str, name: str) -> str:
    text = f"{entity_type} {name}".lower()
    if any(word in text for word in ("settlement", "resident", "村", "组", "居民点")):
        return "settlement_cluster"
    if any(word in text for word in ("industry", "产业", "基地", "园区", "厂")):
        return "industry_node"
    if any(word in text for word in ("tourism", "旅游", "景区", "游客", "民宿")):
        return "tourism_node"
    if any(word in text for word in ("emergency", "消防", "避险", "应急")):
        return "emergency_node"
    if any(word in text for word in ("road_endpoint", "道路", "路口", "入口")):
        return "road_access_node"
    if any(word in text for word in ("facility", "public", "服务", "学校", "卫生", "停车")):
        return "facility_node"
    return "facility_node"


def _context_entity_type(spatial_context: Any) -> Optional[str]:
    if not isinstance(spatial_context, Mapping):
        return None
    value = spatial_context.get("entity_type") or spatial_context.get("type")
    return str(value).lower() if str(value or "").strip() else None


def _context_road_relation(spatial_context: Any) -> Optional[str]:
    if not isinstance(spatial_context, Mapping):
        return None
    value = spatial_context.get("road_relation") or spatial_context.get("relation_to_road")
    return str(value).lower() if str(value or "").strip() else None


def _normalise_context_code(value: Any) -> str:
    return re.sub(r"[\s_\-/]+", "", str(value or "").strip().lower())


def _context_value(spatial_context: Any, *keys: str) -> Optional[str]:
    if not isinstance(spatial_context, Mapping):
        return None
    for key in keys:
        value = spatial_context.get(key)
        if str(value or "").strip():
            return str(value)
    return None


def _context_construction_permission(spatial_context: Any) -> Optional[str]:
    value = _context_value(
        spatial_context,
        "construction_permission",
        "construction",
        "build_permission",
        "development_permission",
    )
    return value.lower() if value else None


def _context_planning_zone(spatial_context: Any) -> Optional[str]:
    value = _context_value(spatial_context, "planning_zone", "zone", "plan_zone")
    return value.lower() if value else None


def _is_existing_road_reference(props: Mapping[str, Any]) -> bool:
    context = props.get("spatial_context") or {}
    entity_type = str(props.get("entity_type") or "").lower()
    source_geometry_type = str(props.get("source_geometry_type") or "").lower()
    spatial_reference_type = str(props.get("spatial_reference_type") or "").lower()
    road_relation = _context_road_relation(context)
    context_type = _context_entity_type(context)
    return (
        entity_type == "road"
        or context_type == "road"
        or road_relation in {"road_segment", "road_crosses", "existing_road", "connected"}
        or source_geometry_type in {"linestring", "multilinestring"}
        or spatial_reference_type in {"linestring", "multilinestring", "road_segment"}
    )


def _restricted_reference_reasons(props: Mapping[str, Any]) -> List[str]:
    context = props.get("spatial_context") or {}
    entity_type = _normalise_context_code(props.get("entity_type") or _context_entity_type(context) or "")
    context_type = _normalise_context_code(_context_entity_type(context) or "")
    permission = _normalise_context_code(
        props.get("construction_permission") or _context_construction_permission(context) or ""
    )
    planning_zone = _normalise_context_code(
        props.get("planning_zone") or _context_planning_zone(context) or ""
    )
    landuse = _normalise_context_code(
        props.get("landuse")
        or props.get("landuse_type")
        or _context_value(context, "landuse", "landuse_type", "land_type")
        or ""
    )
    restricted_permissions = {
        "forbidconstruction",
        "forbidden",
        "noconstruction",
        "prohibitconstruction",
        "notbuildable",
        "banconstruction",
        "\u7981\u6b62\u5efa\u8bbe",
        "\u4e0d\u53ef\u5efa\u8bbe",
    }
    restricted_types = {
        "farmland",
        "cultivatedland",
        "water",
        "waterbody",
        "ecological",
        "ecology",
        "ecologicalprotection",
        "protectedfarmland",
        "basicfarmland",
        "\u8015\u5730",
        "\u6c34\u57df",
        "\u751f\u6001\u7eff\u5730",
    }
    restricted_zones = {
        "farmlandprotection",
        "permanentbasicfarmland",
        "ecologicalprotection",
        "ecologicalredline",
        "waterprotection",
        "\u519c\u7530\u4fdd\u62a4\u533a",
        "\u751f\u6001\u4fdd\u62a4\u533a",
        "\u6c34\u57df",
    }
    reasons: List[str] = []
    if permission in restricted_permissions:
        reasons.append("forbid_construction")
    if entity_type in restricted_types or context_type in restricted_types:
        reasons.append("restricted_entity_type")
    if planning_zone in restricted_zones:
        reasons.append("restricted_planning_zone")
    if landuse in restricted_types:
        reasons.append("restricted_landuse")
    return sorted(set(reasons))


def _is_restricted_spatial_reference(props: Mapping[str, Any]) -> bool:
    return bool(_restricted_reference_reasons(props))


def _is_compound_place(value: Any) -> bool:
    text = str(value or "")
    separators = ("-", "—", "至", "到", "连接", "连通")
    return any(separator in text for separator in separators)


def _recommended_width(action: str, node_type: str) -> float:
    if action == "widen":
        return 5.5
    if node_type in {"industry_node", "emergency_node"}:
        return 4.5
    return 3.5


def _source_kind(path: Path) -> str:
    lower = path.as_posix().lower()
    if "annotation" in lower:
        return "annotation"
    if "poi" in lower or "amap" in lower or "gazetteer" in lower:
        return "local_poi"
    return "project_gis"


def _status(distance_m: Optional[float], config: PlanningNodeBuildConfig) -> str:
    if distance_m is None:
        return "unresolved"
    if distance_m <= config.connected_threshold_m:
        return "connected"
    if distance_m <= config.near_network_threshold_m:
        return "near_network"
    return "isolated"


def _nearest_road(point: Point, roads: gpd.GeoDataFrame) -> Tuple[Optional[str], Optional[Point], Optional[float]]:
    if roads.empty:
        return None, None, None
    distances = roads.geometry.distance(point)
    minimum = float(distances.min())
    tolerance = max(1e-8, minimum * 1e-12)
    row = roads.loc[(distances - minimum).abs() <= tolerance].sort_values("edge_id", kind="stable").iloc[0]
    snapped = nearest_points(point, row.geometry)[1]
    return str(row.get("edge_id")), snapped, float(point.distance(snapped))


def _prepare_roads(config: PlanningNodeBuildConfig) -> gpd.GeoDataFrame:
    roads = gpd.read_file(config.road_edges_path)
    if roads.crs is None:
        raise ValueError(f"road edges have no CRS: {config.road_edges_path}")
    roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
    roads = roads[roads.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    if roads.empty:
        raise ValueError("standardized current-road input contains no usable line geometry")
    roads = roads.to_crs(config.metric_crs)
    if "edge_id" not in roads.columns:
        roads["edge_id"] = [f"E{index + 1:06d}" for index in range(len(roads))]
    return roads.sort_values("edge_id", kind="stable").reset_index(drop=True)


def _prepare_boundary(config: PlanningNodeBuildConfig) -> Optional[Any]:
    if config.boundary_path is None:
        return None
    boundary = gpd.read_file(config.boundary_path)
    if boundary.crs is None:
        raise ValueError(f"boundary has no CRS: {config.boundary_path}")
    boundary = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty].copy()
    if boundary.empty:
        return None
    return unary_union(boundary.to_crs(config.metric_crs).geometry)


def _point_index(paths: Sequence[Path], display_crs: str) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for path in paths:
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError(f"point source has no CRS: {path}")
        frame = frame.to_crs(display_crs)
        fields = [field for field in NAME_FIELDS if field in frame.columns]
        for feature_index, row in frame.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
                continue
            for field in fields:
                value = row.get(field)
                key = _normalise_name(value)
                if len(key) < 2:
                    continue
                result[key].append(
                    {
                        "name": str(value),
                        "geometry": mapping(geometry),
                        "source": _source_kind(path),
                        "source_path": _relative(path),
                        "feature_index": str(feature_index),
                        "matched_field": field,
                    }
                )
    return result


def _extract_bsms(properties: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for field in BSM_FIELDS:
        if field in properties:
            values.extend(_flatten_string_list(properties.get(field)))
    return sorted(set(value.strip() for value in values if value.strip()))


def _first_property(properties: Mapping[str, Any], *names: str) -> Optional[Any]:
    normalized = {str(key).lower(): value for key, value in properties.items()}
    for name in names:
        for key in (name, name.lower(), name.upper()):
            if key in properties and str(properties.get(key) or "").strip():
                return properties.get(key)
        value = normalized.get(name.lower())
        if str(value or "").strip():
            return value
    return None


def _bundle_spatial_context(properties: Mapping[str, Any]) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    field_map = {
        "entity_type": ("entity_type", "feature_type", "type", "layer_type", "landuse_type", "landuse"),
        "landuse": ("landuse", "landuse_type", "DLMC", "dlmc", "地类", "地类名称"),
        "planning_zone": ("planning_zone", "plan_zone", "zone", "zone_type", "规划分区"),
        "construction_permission": (
            "construction_permission",
            "build_permission",
            "development_permission",
            "allow_construction",
            "建设许可",
        ),
        "road_relation": ("road_relation", "relation_to_road"),
    }
    for target, aliases in field_map.items():
        value = _first_property(properties, *aliases)
        if value is not None:
            context[target] = value
    return context


def _merge_spatial_contexts(*contexts: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for context in contexts:
        if not isinstance(context, Mapping):
            continue
        for key, value in context.items():
            if key not in merged and str(value or "").strip():
                merged[key] = value
    return merged


def _geometry_index(paths: Sequence[Path], display_crs: str) -> Dict[str, Dict[str, Any]]:
    """Index bundle geometries by BSM without exposing answer/planned layers."""

    result: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError(f"bundle geometry source has no CRS: {path}")
        frame = frame.to_crs(display_crs)
        for feature_index, row in frame.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                continue
            properties = {key: _safe_jsonable(row.get(key)) for key in frame.columns if key != "geometry"}
            for bsm in _extract_bsms(properties):
                result.setdefault(
                    bsm,
                    {
                        "bsm": bsm,
                        "geometry": mapping(geometry),
                        "geometry_type": geometry.geom_type,
                        "source_path": _relative(path),
                        "feature_index": str(feature_index),
                        "properties": properties,
                    },
                )
    return result


def _records_from_kg_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        records = []
        for feature_index, feature in enumerate(payload.get("features", [])):
            properties = dict(feature.get("properties") or {})
            records.append(
                {
                    **properties,
                    "geometry": feature.get("geometry"),
                    "feature_index": feature_index,
                }
            )
        return records
    if isinstance(payload, Mapping):
        records = payload.get("entities") or payload.get("locations") or payload.get("candidates") or []
        return [dict(item) for item in records if isinstance(item, Mapping)]
    return []


def _records_from_confirmation_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        return _records_from_kg_payload(payload)
    if isinstance(payload, Mapping):
        records = (
            payload.get("confirmations")
            or payload.get("entities")
            or payload.get("locations")
            or payload.get("candidates")
            or []
        )
        return [dict(item) for item in records if isinstance(item, Mapping)]
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _record_alias_keys(record: Mapping[str, Any]) -> List[Any]:
    aliases = _string_list(record.get("aliases"))
    ids = _string_list(
        [
            record.get("entity_id"),
            record.get("source_entity_id"),
            record.get("demand_id"),
            record.get("planning_node_id"),
            record.get("kg_entity_id"),
        ]
    )
    name = record.get("name") or record.get("canonical_name")
    target_ids = _string_list([record.get("target_id"), record.get("review_target_id")])
    return [name, record.get("canonical_name"), *aliases, *ids, *target_ids]


def _manual_confirmation_indexes(
    path: Optional[Path],
    bundle_index: Mapping[str, Dict[str, Any]],
    roads: gpd.GeoDataFrame,
    config: PlanningNodeBuildConfig,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]], int]:
    point_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    spatial_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    spatial_candidates: List[Dict[str, Any]] = []
    if path is None:
        return point_index, spatial_index, spatial_candidates, 0

    payload = _read_json(path)
    crs = _collection_crs(payload, config.display_crs) if isinstance(payload, Mapping) else config.display_crs
    records = _records_from_confirmation_payload(payload)
    accepted_count = 0
    for feature_index, record in enumerate(records):
        status = str(record.get("confirmation_status") or record.get("status") or "confirmed").lower()
        if status not in {"confirmed", "accepted", "manual_confirmed", "resolved"}:
            continue
        accepted_count += 1
        geometry_payload = record.get("geometry")
        if not geometry_payload and record.get("lon") is not None and record.get("lat") is not None:
            geometry_payload = {
                "type": "Point",
                "coordinates": [float(record["lon"]), float(record["lat"])],
            }
        bsm_list = _flatten_string_list(
            record.get("bsm_list")
            or record.get("candidate_bsms")
            or record.get("source_bsms")
            or record.get("path_bsms")
            or record.get("bsm")
        )
        bbox_values = _bbox_list(record.get("candidate_bbox") or record.get("bbox") or record.get("bounds"))
        geometry_type = shape(geometry_payload).geom_type if geometry_payload else None
        if geometry_payload and geometry_type == "Point" and not bsm_list and not bbox_values:
            point = _transform(shape(geometry_payload), _transformer(crs, config.display_crs))
            candidate = {
                "candidate_id": str(record.get("candidate_id") or f"MAN-{feature_index + 1:04d}"),
                "name": str(record.get("name") or record.get("target_id") or record.get("entity_id") or ""),
                "geometry": mapping(point),
                "source": "manual",
                "source_path": _relative(path),
                "feature_index": str(feature_index),
                "matched_field": "manual_confirmation",
                "confidence": float(record.get("confidence") or 1.0),
                "location_resolver_source": "manual_confirmation",
                "target_id": record.get("target_id"),
                "kg_entity_id": record.get("kg_entity_id") or record.get("entity_id"),
                "is_manual_confirmation": True,
                "requires_human_confirmation": False,
            }
            _add_candidate(point_index, candidate, _record_alias_keys(record))
            continue

        candidate = _spatial_candidate_from_record(
            record,
            str(record.get("candidate_id") or f"MAN-{feature_index + 1:04d}"),
            _relative(path),
            feature_index,
            bundle_index,
            roads,
            config,
            crs,
            "manual",
            "manual_confirmation",
        )
        if candidate is None:
            continue
        spatial_candidates.append(candidate)
        _add_candidate(spatial_index, candidate, _record_alias_keys(record))
    return point_index, spatial_index, spatial_candidates, accepted_count


def _geometry_access_point(geometry: Any, roads: gpd.GeoDataFrame, config: PlanningNodeBuildConfig) -> Point:
    if geometry.geom_type == "Point":
        return geometry
    metric_geometry = _transform(geometry, _transformer(config.display_crs, config.metric_crs))
    if metric_geometry.geom_type in {"LineString", "MultiLineString"}:
        point_metric = metric_geometry.interpolate(0.5, normalized=True)
    elif roads.empty:
        point_metric = metric_geometry.representative_point()
    else:
        road_union = unary_union(roads.geometry)
        _, point_metric = nearest_points(road_union, metric_geometry)
    return _transform(point_metric, _transformer(config.metric_crs, config.display_crs))


def _bsm_bundle_summary(bsms: Sequence[str], bundle_index: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for bsm in bsms:
        record = bundle_index.get(bsm)
        if record is None:
            summaries.append({"bsm": bsm, "resolved": False})
        else:
            summaries.append(
                {
                    "bsm": bsm,
                    "resolved": True,
                    "geometry_type": record.get("geometry_type"),
                    "source_path": record.get("source_path"),
                    "feature_index": record.get("feature_index"),
                    "spatial_context": _bundle_spatial_context(record.get("properties") or {}),
                }
            )
    return summaries


def _bundle_context_for_bsms(
    bsms: Sequence[str],
    bundle_index: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any]:
    contexts = [
        _bundle_spatial_context((bundle_index.get(bsm) or {}).get("properties") or {})
        for bsm in bsms
        if bundle_index.get(bsm)
    ]
    return _merge_spatial_contexts(*contexts)


def _spatial_candidate_from_record(
    record: Mapping[str, Any],
    candidate_id: str,
    source_path: str,
    feature_index: int,
    bundle_index: Mapping[str, Dict[str, Any]],
    roads: gpd.GeoDataFrame,
    config: PlanningNodeBuildConfig,
    source_crs: str,
    default_source: str,
    resolver_source: str,
) -> Optional[Dict[str, Any]]:
    bsm_list = sorted(
        set(
            _flatten_string_list(
                record.get("bsm_list")
                or record.get("candidate_bsms")
                or record.get("source_bsm_list")
                or record.get("source_bsms")
                or record.get("path_bsms")
                or record.get("bsm")
            )
        )
    )
    bbox_values = _bbox_list(record.get("candidate_bbox") or record.get("bbox") or record.get("bounds"))
    geometry_payload = record.get("geometry")
    if not geometry_payload and bbox_values:
        geometry_payload = mapping(box(*bbox_values))
    if not geometry_payload and record.get("lon") is not None and record.get("lat") is not None:
        geometry_payload = {
            "type": "Point",
            "coordinates": [float(record["lon"]), float(record["lat"])],
        }

    geometries = []
    for bsm in bsm_list:
        bundle_record = bundle_index.get(bsm)
        if bundle_record and bundle_record.get("geometry"):
            geometries.append(shape(bundle_record["geometry"]))
    geometry = None
    if geometry_payload:
        geometry = _transform(shape(geometry_payload), _transformer(source_crs, config.display_crs))
    elif geometries:
        geometry = unary_union(geometries)
    if geometry is None and not bsm_list:
        return None

    reference_type = str(record.get("spatial_reference_type") or "")
    if not reference_type:
        if bsm_list:
            reference_type = "bsm_list"
        elif bbox_values:
            reference_type = "bbox"
        elif geometry is not None:
            reference_type = geometry.geom_type.lower()
        else:
            reference_type = "entity"
    access_point = _geometry_access_point(geometry, roads, config) if geometry is not None else None
    summaries = _bsm_bundle_summary(bsm_list, bundle_index)
    name = str(
        record.get("name")
        or record.get("canonical_name")
        or record.get("entity_id")
        or record.get("kg_entity_id")
        or record.get("target_id")
        or candidate_id
    )
    is_manual = resolver_source == "manual_confirmation"
    requires_confirmation = bool(record.get("requires_human_confirmation"))
    if str(record.get("confirmation_status") or "").lower() in {"confirmed", "accepted", "manual_confirmed"}:
        requires_confirmation = False
    bundle_context = _bundle_context_for_bsms(bsm_list, bundle_index)
    explicit_context = record.get("spatial_context") or record.get("context") or {}
    return {
        "candidate_id": candidate_id,
        "name": name,
        "geometry": mapping(access_point) if access_point is not None else None,
        "display_geometry": mapping(geometry) if geometry is not None else None,
        "source_geometry_type": geometry.geom_type if geometry is not None else None,
        "source": str(record.get("source") or default_source),
        "source_path": source_path,
        "feature_index": str(record.get("feature_index", feature_index)),
        "matched_field": str(record.get("matched_field") or "spatial_reference"),
        "confidence": float(record.get("confidence") or (1.0 if is_manual else 0.82)),
        "location_resolver_source": resolver_source,
        "kg_entity_id": record.get("kg_entity_id") or record.get("entity_id"),
        "target_id": record.get("target_id"),
        "spatial_reference_type": reference_type,
        "candidate_bsm_list": bsm_list,
        "candidate_bbox": bbox_values,
        "bundle_geometry_summaries": summaries,
        "spatial_context": _merge_spatial_contexts(explicit_context, bundle_context),
        "bundle_spatial_context": bundle_context,
        "is_manual_confirmation": is_manual,
        "requires_human_confirmation": requires_confirmation
        or str(record.get("binding_status") or "") not in {"", "confirmed"}
        or reference_type == "bbox"
        or (bool(bsm_list) and any(item.get("resolved") is False for item in summaries)),
    }


def _spatial_candidate_index(
    path: Optional[Path],
    bundle_index: Mapping[str, Dict[str, Any]],
    roads: gpd.GeoDataFrame,
    config: PlanningNodeBuildConfig,
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Index KG spatial references that are richer than one direct point.

    The KG bridge may return BSM lists, candidate bboxes, polygons, lines, or
    points.  BSM references are resolved against local bundle geometry sources.
    """

    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    candidates: List[Dict[str, Any]] = []
    if path is None:
        return result, candidates

    payload = _read_json(path)
    source_crs = _collection_crs(payload, config.display_crs) if isinstance(payload, Mapping) else config.display_crs
    for feature_index, record in enumerate(_records_from_kg_payload(payload)):
        candidate = _spatial_candidate_from_record(
            record,
            str(record.get("candidate_id") or f"KGC-{feature_index + 1:04d}"),
            _relative(path),
            feature_index,
            bundle_index,
            roads,
            config,
            source_crs,
            "gazetteer",
            "knowledge_graph",
        )
        if candidate is None:
            continue
        candidates.append(candidate)
        _add_candidate(result, candidate, _record_alias_keys(record))
    return result, candidates


def _stage2_entity_spatial_index(
    entities: Sequence[Mapping[str, Any]],
    bundle_index: Mapping[str, Dict[str, Any]],
    roads: gpd.GeoDataFrame,
    config: PlanningNodeBuildConfig,
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    candidates: List[Dict[str, Any]] = []
    for feature_index, entity in enumerate(entities):
        bsm_list = sorted(set(_flatten_string_list(entity.get("candidate_bsm_list"))))
        bbox_values = _bbox_list(entity.get("candidate_bbox"))
        if not bsm_list and not bbox_values:
            continue
        geometries = [
            shape(bundle_index[bsm]["geometry"])
            for bsm in bsm_list
            if bsm in bundle_index and bundle_index[bsm].get("geometry")
        ]
        geometry = unary_union(geometries) if geometries else None
        if geometry is None and bbox_values:
            geometry = box(*bbox_values)
        access_point = _geometry_access_point(geometry, roads, config) if geometry is not None else None
        reference_type = "bsm_list" if bsm_list else "bbox"
        bundle_context = _bundle_context_for_bsms(bsm_list, bundle_index)
        candidate = {
            "candidate_id": f"S2C-{feature_index + 1:04d}",
            "name": str(entity.get("name") or entity.get("entity_id") or f"stage2_candidate_{feature_index + 1}"),
            "geometry": mapping(access_point) if access_point is not None else None,
            "display_geometry": mapping(geometry) if geometry is not None else None,
            "source_geometry_type": geometry.geom_type if geometry is not None else None,
            "source": str(entity.get("source") or "project_gis"),
            "source_path": "stage2_structured_intent",
            "feature_index": str(feature_index),
            "matched_field": "stage2_bsm_or_bbox",
            "confidence": float(entity.get("confidence") or 0.72),
            "location_resolver_source": "stage2_spatial_reference",
            "kg_entity_id": entity.get("kg_entity_id"),
            "spatial_reference_type": reference_type,
            "candidate_bsm_list": bsm_list,
            "candidate_bbox": bbox_values,
            "bundle_geometry_summaries": _bsm_bundle_summary(bsm_list, bundle_index),
            "spatial_context": bundle_context,
            "bundle_spatial_context": bundle_context,
            "requires_human_confirmation": reference_type == "bbox"
            or any(item.get("resolved") is False for item in _bsm_bundle_summary(bsm_list, bundle_index)),
        }
        candidates.append(candidate)
        _add_candidate(result, candidate, [entity.get("name"), entity.get("entity_id")])
    return result, candidates


def _add_candidate(
    index: Dict[str, List[Dict[str, Any]]],
    candidate: Dict[str, Any],
    keys: Iterable[Any],
) -> None:
    for key_value in keys:
        key = _normalise_name(key_value)
        if len(key) < 2:
            continue
        index[key].append(candidate)


def _knowledge_graph_index(path: Optional[Path], display_crs: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read KG-derived entity locations into the same resolver index as POI layers.

    Supported demo/adapter shapes:
      - GeoJSON FeatureCollection with Point features.
      - {"entities": [...]} or {"locations": [...]} with geometry or lon/lat.

    The public ``source`` is kept as ``gazetteer`` to satisfy the Stage-2.6
    output enum, while ``location_resolver_source`` records that the candidate
    came from the KG bridge.
    """

    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if path is None:
        return result
    payload = _read_json(path)
    crs = _collection_crs(payload, display_crs) if isinstance(payload, Mapping) else display_crs
    transformer = _transformer(crs, display_crs)
    records = _records_from_kg_payload(payload)
    for feature_index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        geometry_payload = record.get("geometry")
        if not geometry_payload and record.get("lon") is not None and record.get("lat") is not None:
            geometry_payload = {
                "type": "Point",
                "coordinates": [float(record["lon"]), float(record["lat"])],
            }
        if not geometry_payload:
            continue
        point = shape(geometry_payload)
        if point.is_empty or point.geom_type != "Point":
            continue
        point = _transform(point, transformer)
        aliases = _string_list(record.get("aliases"))
        ids = _string_list(
            [
                record.get("entity_id"),
                record.get("source_entity_id"),
                record.get("demand_id"),
                record.get("planning_node_id"),
                record.get("kg_entity_id"),
            ]
        )
        name = str(record.get("name") or record.get("canonical_name") or next(iter(aliases), "") or next(iter(ids), ""))
        candidate = {
            "name": name,
            "geometry": mapping(point),
            "source": str(record.get("source") or "gazetteer"),
            "source_path": _relative(path),
            "feature_index": str(record.get("feature_index", feature_index)),
            "matched_field": "kg_entity_or_alias",
            "confidence": float(record.get("confidence") or 0.92),
            "location_resolver_source": "knowledge_graph",
            "kg_entity_id": record.get("kg_entity_id") or record.get("entity_id"),
        }
        _add_candidate(result, candidate, [name, record.get("canonical_name"), *aliases, *ids])
    return result


def _merge_indexes(*indexes: Mapping[str, Sequence[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    merged: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for index in indexes:
        for key, values in index.items():
            merged[key].extend(values)
    return merged


def _match_candidates(index: Mapping[str, Sequence[Dict[str, Any]]], names: Iterable[Any]) -> List[Dict[str, Any]]:
    matches: Dict[str, Dict[str, Any]] = {}
    for name in names:
        key = _normalise_name(name)
        if not key:
            continue
        for candidate in index.get(key, ()):
            candidate_key = json.dumps(
                candidate.get("geometry") or candidate.get("candidate_id") or candidate,
                sort_keys=True,
                ensure_ascii=False,
            )
            matches.setdefault(candidate_key, candidate)
    return list(matches.values())


def _load_chunks(stage2_dir: Path) -> List[Mapping[str, Any]]:
    for name in ("text_chunks.json", "chunks.json", "document_chunks.json"):
        path = stage2_dir / name
        if not path.exists():
            continue
        payload = _read_json(path)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, Mapping)]
        if isinstance(payload, Mapping):
            chunks = payload.get("chunks") or payload.get("items") or []
            return [item for item in chunks if isinstance(item, Mapping)]
    path = stage2_dir / "text_chunks.jsonl"
    if path.exists():
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    return []


def _rule_intents_from_chunks(chunks: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<start>[\u4e00-\u9fa5A-Za-z0-9（）()]{2,30})\s*(?:至|到|连接|连通|接入)\s*"
        r"(?P<end>[\u4e00-\u9fa5A-Za-z0-9（）()]{2,30})"
    )
    for chunk in chunks:
        text = str(chunk.get("text") or chunk.get("content") or "")
        if not any(keyword in text for words in ROAD_ACTIONS.values() for keyword in words):
            continue
        for match in pattern.finditer(text):
            start = match.group("start").strip("，。；;:： ")
            end = match.group("end").strip("，。；;:： ")
            if not start or not end:
                continue
            intent_index = len(intents) + 1
            intents.append(
                {
                    "intent_id": f"RI-C{intent_index:04d}",
                    "task_type": "road_connection",
                    "action": _action_from_text(text),
                    "start_place": start,
                    "end_place": end,
                    "mentioned_places": sorted({start, end}),
                    "served_objects": [],
                    "constraints": [],
                    "evidence_text": text,
                    "source_chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
                    "section_title": chunk.get("section_title") or chunk.get("section"),
                    "source_page": chunk.get("source_page") or chunk.get("page"),
                    "confidence": 0.72,
                    "requires_human_confirmation": False,
                    "extraction_method": "rule_chunk",
                }
            )
    return intents


def _rule_intents_from_chunks(chunks: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    place = r"[\u4e00-\u9fa5A-Za-z0-9_\u00b7\uff08\uff09()]{2,40}"
    connection_patterns = [
        re.compile(
            rf"(?:\u89c4\u5212|\u65b0\u5efa|\u65b0\u589e|\u5b8c\u5584|\u6253\u901a|\u8fde\u901a|\u8fde\u63a5|\u63a5\u5165)?"
            rf"(?P<start>{place})\s*(?:\u81f3|\u5230|\u901a\u5f80|\u8fde\u63a5|\u8fde\u901a|\u63a5\u5165|\u8d2f\u901a|[-\u2014~\uff5e])\s*"
            rf"(?P<end>{place})(?:{ROAD_NOUN_PATTERN})?"
        ),
        re.compile(
            rf"(?:\u6253\u901a|\u8fde\u901a|\u8fde\u63a5|\u63a5\u5165|\u8d2f\u901a|\u8054\u7cfb)"
            rf"(?P<start>{place})\s*(?:\u4e0e|\u548c|\u53ca|\u81f3|\u5230)\s*"
            rf"(?P<end>{place})(?:{ROAD_NOUN_PATTERN})?"
        ),
    ]
    upgrade_patterns = [
        re.compile(
            rf"(?P<verb>\u62d3\u5bbd|\u6269\u5bbd|\u52a0\u5bbd|\u786c\u5316|\u9ed1\u5316|\u94fa\u88c5|\u4fee\u590d|\u4fee\u7f2e|\u6574\u6cbb|\u63d0\u5347|\u6539\u9020|\u5b8c\u5584)"
            rf"(?P<target>{place})(?:{ROAD_NOUN_PATTERN})"
        ),
        re.compile(
            rf"(?P<target>{place})(?:{ROAD_NOUN_PATTERN})"
            rf"(?P<verb>\u62d3\u5bbd|\u6269\u5bbd|\u52a0\u5bbd|\u786c\u5316|\u9ed1\u5316|\u94fa\u88c5|\u4fee\u590d|\u4fee\u7f2e|\u6574\u6cbb|\u63d0\u5347|\u6539\u9020|\u5b8c\u5584)"
        ),
    ]
    seen: set[Tuple[str, str, str]] = set()
    for chunk in chunks:
        text = str(chunk.get("text") or chunk.get("content") or "")
        if not _has_road_action_text(text):
            continue
        for pattern in connection_patterns:
            for match in pattern.finditer(text):
                start = _clean_extracted_place(match.group("start"))
                end = _clean_extracted_place(match.group("end"))
                if not start or not end:
                    continue
                action = _action_from_text(text)
                key = (_normalise_name(start), _normalise_name(end), action)
                if key in seen:
                    continue
                seen.add(key)
                intent_index = len(intents) + 1
                intents.append(
                    {
                        "intent_id": f"RI-C{intent_index:04d}",
                        "task_type": "road_connection",
                        "action": action,
                        "start_place": start,
                        "end_place": end,
                        "mentioned_places": sorted({start, end}),
                        "served_objects": [],
                        "constraints": [],
                        "evidence_text": text,
                        "source_chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
                        "section_title": chunk.get("section_title") or chunk.get("section"),
                        "source_page": chunk.get("source_page") or chunk.get("page"),
                        "confidence": 0.74,
                        "requires_human_confirmation": False,
                        "extraction_method": "rule_chunk",
                    }
                )
        for pattern in upgrade_patterns:
            for match in pattern.finditer(text):
                target = _clean_extracted_place(match.group("target"))
                verb = str(match.group("verb") or "")
                if not target:
                    continue
                action = _action_from_text(verb)
                if action == "new":
                    continue
                key = (_normalise_name(target), "", action)
                if key in seen:
                    continue
                seen.add(key)
                intent_index = len(intents) + 1
                intents.append(
                    {
                        "intent_id": f"RI-C{intent_index:04d}",
                        "task_type": _task_type(action),
                        "action": action,
                        "start_place": target,
                        "end_place": "",
                        "mentioned_places": [target],
                        "served_objects": [],
                        "constraints": [],
                        "evidence_text": text,
                        "source_chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
                        "section_title": chunk.get("section_title") or chunk.get("section"),
                        "source_page": chunk.get("source_page") or chunk.get("page"),
                        "confidence": 0.7,
                        "requires_human_confirmation": False,
                        "extraction_method": "rule_chunk",
                    }
                )
    return intents


def _road_intents(stage2_dir: Path) -> List[Dict[str, Any]]:
    projects_payload = _read_json(stage2_dir / "road_projects.json")
    projects = projects_payload.get("projects", []) if isinstance(projects_payload, Mapping) else []
    intents: List[Dict[str, Any]] = []
    for index, project in enumerate(projects, start=1):
        if not isinstance(project, Mapping):
            continue
        text = _evidence_text(project)
        typed_contract = project.get("typed_contract_version") == "road-planning-input-v1"
        action = (
            str(project.get("action") or "")
            if typed_contract
            else _action_from_text(text, project.get("action"))
        )
        start_place = str(project.get("start_place") or "")
        end_place = str(project.get("end_place") or "")
        source_chunk_id = _source_chunk_id(project)
        section_title = _section_title(project)
        source_page = _source_page(project)
        start_endpoint = project.get("start_endpoint_evidence") or {}
        end_endpoint = project.get("end_endpoint_evidence") or {}
        routing_evidence = project.get("routing_evidence") or {}
        typed_endpoint_provenance = bool(
            typed_contract
            and isinstance(start_endpoint, Mapping)
            and isinstance(end_endpoint, Mapping)
            and start_endpoint.get("resolution_status") == "resolved"
            and end_endpoint.get("resolution_status") == "resolved"
            and start_endpoint.get("source_artifact_ref")
            and end_endpoint.get("source_artifact_ref")
            and start_endpoint.get("evidence_refs")
            and end_endpoint.get("evidence_refs")
            and project.get("start_geometry")
            and project.get("end_geometry")
            and isinstance(routing_evidence, Mapping)
            and any(
                routing_evidence.get(name)
                for name in ("current_network", "dem", "land_friction")
            )
        )
        has_provenance = typed_endpoint_provenance or bool(
            text or source_chunk_id or section_title or source_page is not None
        )
        project_name_mentions = [] if typed_contract else [str(project.get("name") or "")]
        mentioned = sorted(
            {
                item
                for item in [
                    start_place,
                    end_place,
                    *project_name_mentions,
                    *_string_list(project.get("service_places")),
                    *_string_list(project.get("served_objects")),
                ]
                if item.strip()
            }
        )
        confidence = float(project.get("confidence") or (0.99 if typed_contract else 0.82))
        requires_review = (
            bool(project.get("requires_human_confirmation"))
            or confidence < 0.65
            or not has_provenance
        )
        if action == "new" and (not start_place or not end_place):
            requires_review = True
            confidence = min(confidence, 0.6)
        if not has_provenance:
            confidence = min(confidence, 0.6)
        intents.append(
            {
                "intent_id": str(project.get("intent_id") or f"RI-P{index:04d}"),
                "task_type": _task_type(action),
                "action": action,
                "start_place": start_place,
                "end_place": end_place,
                "mentioned_places": mentioned,
                "served_objects": _string_list(project.get("served_objects") or project.get("service_places")),
                "constraints": _as_list(project.get("constraints")),
                "evidence_text": text,
                "source_chunk_id": source_chunk_id,
                "section_title": section_title,
                "source_page": source_page,
                "confidence": round(confidence, 3),
                "requires_human_confirmation": requires_review,
                "project_id": project.get("project_id"),
                "target_id": project.get("target_id") or project.get("project_id"),
                "recommended_road_class": project.get("recommended_road_class") or "village_road",
                "recommended_width_m": project.get("recommended_width_m"),
                "path_bsms": _string_list(project.get("path_bsms")),
                "candidate_bsms": _string_list(project.get("candidate_bsms")),
                "candidate_bbox": project.get("candidate_bbox") or project.get("bbox"),
                "extraction_method": (
                    "typed_road_planning_input" if typed_contract else "stage2_project"
                ),
            }
        )
    chunk_intents = _rule_intents_from_chunks(_load_chunks(stage2_dir))
    existing_keys = {
        (_normalise_name(item.get("start_place")), _normalise_name(item.get("end_place")), item.get("action"))
        for item in intents
    }
    for intent in chunk_intents:
        key = (
            _normalise_name(intent.get("start_place")),
            _normalise_name(intent.get("end_place")),
            intent.get("action"),
        )
        if key not in existing_keys:
            intents.append(intent)
            existing_keys.add(key)
    return intents


def _entities_from_demands(stage2_dir: Path) -> Tuple[List[Dict[str, Any]], str]:
    payload = _read_json(stage2_dir / "demand_points.geojson")
    source_crs = _collection_crs(payload, "EPSG:4326")
    entities: List[Dict[str, Any]] = []
    for index, feature in enumerate(payload.get("features", []), start=1):
        properties = dict(feature.get("properties") or {})
        demand_id = str(properties.get("demand_id") or feature.get("id") or f"D{index:04d}")
        name = str(properties.get("place_name") or properties.get("name") or demand_id)
        text = _evidence_text(properties)
        confidence = float(properties.get("confidence") or properties.get("location_confidence") or 0.72)
        entities.append(
            {
                "entity_id": f"ENT-D-{demand_id}",
                "name": name,
                "entity_type": str(properties.get("demand_type") or "demand"),
                "geometry": feature.get("geometry"),
                "geometry_crs": source_crs,
                "source": str(properties.get("location_source") or "project_gis"),
                "source_intent_ids": _string_list(properties.get("source_intent_ids")),
                "source_chunk_ids": [item for item in [_source_chunk_id(properties)] if item],
                "evidence_texts": [text] if text else [],
                "confidence": confidence,
                "priority": _priority(properties),
                "candidate_bsm_list": _flatten_string_list(
                    properties.get("candidate_bsms")
                    or properties.get("source_bsms")
                    or properties.get("path_bsms")
                    or properties.get("bsm")
                ),
                "candidate_bbox": properties.get("candidate_bbox") or properties.get("bbox"),
                "requires_human_confirmation": bool(properties.get("requires_human_confirmation")),
                "origin": "stage2_demand",
            }
        )
    return entities, source_crs


def _entities_from_intents(intents: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    for intent in intents:
        intent_id = str(intent.get("intent_id") or "")
        chunk_id = str(intent.get("source_chunk_id") or "")
        evidence = str(intent.get("evidence_text") or "")
        for role, place in (("start", intent.get("start_place")), ("end", intent.get("end_place"))):
            name = str(place or "").strip()
            if not name:
                continue
            entities.append(
                {
                    "entity_id": f"ENT-R-{intent_id}-{role}",
                    "name": name,
                    "entity_type": "road_endpoint",
                    "geometry": None,
                    "geometry_crs": None,
                    "source": "unresolved",
                    "source_intent_ids": [intent_id],
                    "intent_roles": [{"intent_id": intent_id, "role": role}],
                    "source_chunk_ids": [chunk_id] if chunk_id else [],
                    "evidence_texts": [evidence] if evidence else [],
                    "confidence": min(float(intent.get("confidence") or 0.6), 0.78),
                    "priority": "high" if intent.get("action") == "new" else "medium",
                    "candidate_bsm_list": _flatten_string_list(
                        intent.get("candidate_bsms") or intent.get("path_bsms")
                    ),
                    "candidate_bbox": intent.get("candidate_bbox") or intent.get("bbox"),
                    "requires_human_confirmation": bool(intent.get("requires_human_confirmation")),
                    "origin": f"road_intent_{role}",
                }
            )
        for place in _string_list(intent.get("served_objects")):
            if _is_compound_place(place):
                continue
            entities.append(
                {
                    "entity_id": f"ENT-S-{intent_id}-{len(entities) + 1:04d}",
                    "name": place,
                    "entity_type": "served_object",
                    "geometry": None,
                    "geometry_crs": None,
                    "source": "unresolved",
                    "source_intent_ids": [intent_id],
                    "intent_roles": [{"intent_id": intent_id, "role": "served"}],
                    "source_chunk_ids": [chunk_id] if chunk_id else [],
                    "evidence_texts": [evidence] if evidence else [],
                    "confidence": min(float(intent.get("confidence") or 0.6), 0.72),
                    "priority": "medium",
                    "requires_human_confirmation": bool(intent.get("requires_human_confirmation")),
                    "origin": "road_intent_served_object",
                }
            )
    return entities


def _merge_entities(entities: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for entity in entities:
        key = _normalise_name(entity.get("name"))
        if not key:
            key = str(entity.get("entity_id"))
        if key not in merged:
            merged[key] = json.loads(json.dumps(entity, ensure_ascii=False))
            continue
        target = merged[key]
        for field in ("source_intent_ids", "source_chunk_ids", "evidence_texts"):
            values = sorted(set(_string_list(target.get(field)) + _string_list(entity.get(field))))
            target[field] = values
        target_roles = _intent_role_list(target.get("intent_roles"))
        incoming_roles = _intent_role_list(entity.get("intent_roles"))
        role_keys = {(item["intent_id"], item["role"]) for item in target_roles}
        for item in incoming_roles:
            key = (item["intent_id"], item["role"])
            if key not in role_keys:
                target_roles.append(item)
                role_keys.add(key)
        target["intent_roles"] = target_roles
        target["candidate_bsm_list"] = sorted(
            set(_string_list(target.get("candidate_bsm_list")) + _string_list(entity.get("candidate_bsm_list")))
        )
        if not target.get("candidate_bbox") and entity.get("candidate_bbox"):
            target["candidate_bbox"] = entity.get("candidate_bbox")
        target["confidence"] = max(float(target.get("confidence") or 0), float(entity.get("confidence") or 0))
        target["requires_human_confirmation"] = bool(target.get("requires_human_confirmation")) or bool(
            entity.get("requires_human_confirmation")
        )
        if not target.get("geometry") and entity.get("geometry"):
            target["geometry"] = entity["geometry"]
            target["geometry_crs"] = entity.get("geometry_crs")
            target["source"] = entity.get("source")
        if _priority_rank(str(entity.get("priority") or "medium")) > _priority_rank(
            str(target.get("priority") or "medium")
        ):
            target["priority"] = entity.get("priority")
    return list(merged.values())


def _locate_entities(
    entities: Sequence[Dict[str, Any]],
    manual_point_index: Mapping[str, Sequence[Dict[str, Any]]],
    point_index: Mapping[str, Sequence[Dict[str, Any]]],
    manual_spatial_index: Mapping[str, Sequence[Dict[str, Any]]],
    spatial_index: Mapping[str, Sequence[Dict[str, Any]]],
    roads: gpd.GeoDataFrame,
    boundary_metric: Optional[Any],
    config: PlanningNodeBuildConfig,
) -> List[Dict[str, Any]]:
    located: List[Dict[str, Any]] = []
    to_display = _transformer(config.metric_crs, config.display_crs)
    for ordinal, source_entity in enumerate(entities, start=1):
        entity = json.loads(json.dumps(source_entity, ensure_ascii=False))
        geometry_payload = entity.get("geometry")
        display_geometry_payload = geometry_payload
        location_status = "confirmed" if geometry_payload else "unresolved"
        candidates: List[Dict[str, Any]] = []
        if not geometry_payload:
            candidates = _match_candidates(manual_point_index, (entity.get("name"), entity.get("entity_id")))
            if len(candidates) == 1:
                geometry_payload = candidates[0]["geometry"]
                display_geometry_payload = geometry_payload
                entity["source"] = candidates[0]["source"]
                entity["source_path"] = candidates[0]["source_path"]
                location_status = "confirmed"
                entity["confidence"] = max(
                    float(entity.get("confidence") or 0.7),
                    float(candidates[0].get("confidence") or 0.0),
                )
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
                entity["kg_entity_id"] = candidates[0].get("kg_entity_id")
                if candidates[0].get("is_manual_confirmation"):
                    entity["requires_human_confirmation"] = False
            elif len(candidates) > 1:
                location_status = "candidate"
                entity["source"] = candidates[0]["source"]
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
                entity["candidate_summaries"] = [
                    {key: value for key, value in candidate.items() if key != "geometry"}
                    for candidate in candidates[:10]
                ]
        if not geometry_payload and not candidates:
            candidates = _match_candidates(point_index, (entity.get("name"), entity.get("entity_id")))
            if len(candidates) == 1:
                geometry_payload = candidates[0]["geometry"]
                display_geometry_payload = geometry_payload
                entity["source"] = candidates[0]["source"]
                entity["source_path"] = candidates[0]["source_path"]
                location_status = "confirmed"
                entity["confidence"] = max(
                    min(1.0, float(entity.get("confidence") or 0.7) + 0.18),
                    float(candidates[0].get("confidence") or 0.0),
                )
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
            elif len(candidates) > 1:
                location_status = "candidate"
                entity["source"] = candidates[0]["source"]
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
                entity["candidate_summaries"] = [
                    {key: value for key, value in candidate.items() if key != "geometry"}
                    for candidate in candidates[:10]
                ]
        if not geometry_payload and not candidates:
            candidates = _match_candidates(manual_spatial_index, (entity.get("name"), entity.get("entity_id")))
            if len(candidates) == 1:
                candidate = candidates[0]
                geometry_payload = candidate.get("geometry")
                display_geometry_payload = candidate.get("display_geometry") or geometry_payload
                entity["source"] = candidate.get("source")
                entity["source_path"] = candidate.get("source_path")
                entity["location_resolver_source"] = candidate.get("location_resolver_source")
                entity["kg_entity_id"] = candidate.get("kg_entity_id")
                entity["spatial_reference_type"] = candidate.get("spatial_reference_type")
                entity["candidate_bsm_list"] = candidate.get("candidate_bsm_list")
                entity["candidate_bbox"] = candidate.get("candidate_bbox")
                entity["bundle_geometry_summaries"] = candidate.get("bundle_geometry_summaries")
                entity["source_geometry_type"] = candidate.get("source_geometry_type")
                entity["spatial_context"] = candidate.get("spatial_context")
                entity["bundle_spatial_context"] = candidate.get("bundle_spatial_context")
                entity["access_point_generation_method"] = (
                    "source_point"
                    if candidate.get("source_geometry_type") == "Point"
                    else "nearest_road_side_or_representative_point"
                    if geometry_payload
                    else None
                )
                entity["confidence"] = max(
                    min(1.0, float(entity.get("confidence") or 0.7) + 0.1),
                    float(candidate.get("confidence") or 0.0),
                )
                entity["requires_human_confirmation"] = bool(entity.get("requires_human_confirmation")) or bool(
                    candidate.get("requires_human_confirmation")
                )
                if candidate.get("is_manual_confirmation") and not candidate.get("requires_human_confirmation"):
                    entity["requires_human_confirmation"] = False
                location_status = "confirmed" if geometry_payload else "unresolved"
                if candidate.get("spatial_reference_type") == "bbox":
                    location_status = "candidate"
            elif len(candidates) > 1:
                location_status = "candidate"
                entity["source"] = candidates[0].get("source")
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
                entity["candidate_summaries"] = [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key not in {"geometry", "display_geometry"}
                    }
                    for candidate in candidates[:10]
                ]
        if not geometry_payload and not candidates:
            candidates = _match_candidates(spatial_index, (entity.get("name"), entity.get("entity_id")))
            if len(candidates) == 1:
                candidate = candidates[0]
                geometry_payload = candidate.get("geometry")
                display_geometry_payload = candidate.get("display_geometry") or geometry_payload
                entity["source"] = candidate.get("source")
                entity["source_path"] = candidate.get("source_path")
                entity["location_resolver_source"] = candidate.get("location_resolver_source")
                entity["kg_entity_id"] = candidate.get("kg_entity_id")
                entity["spatial_reference_type"] = candidate.get("spatial_reference_type")
                entity["candidate_bsm_list"] = candidate.get("candidate_bsm_list")
                entity["candidate_bbox"] = candidate.get("candidate_bbox")
                entity["bundle_geometry_summaries"] = candidate.get("bundle_geometry_summaries")
                entity["source_geometry_type"] = candidate.get("source_geometry_type")
                entity["spatial_context"] = candidate.get("spatial_context")
                entity["bundle_spatial_context"] = candidate.get("bundle_spatial_context")
                entity["access_point_generation_method"] = (
                    "source_point"
                    if candidate.get("source_geometry_type") == "Point"
                    else "nearest_road_side_or_representative_point"
                    if geometry_payload
                    else None
                )
                entity["confidence"] = max(
                    min(1.0, float(entity.get("confidence") or 0.7) + 0.1),
                    float(candidate.get("confidence") or 0.0),
                )
                entity["requires_human_confirmation"] = bool(entity.get("requires_human_confirmation")) or bool(
                    candidate.get("requires_human_confirmation")
                )
                location_status = "confirmed" if geometry_payload else "unresolved"
                if candidate.get("spatial_reference_type") == "bbox":
                    location_status = "candidate"
            elif len(candidates) > 1:
                location_status = "candidate"
                entity["source"] = candidates[0].get("source")
                entity["location_resolver_source"] = candidates[0].get("location_resolver_source")
                entity["candidate_summaries"] = [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key not in {"geometry", "display_geometry"}
                    }
                    for candidate in candidates[:10]
                ]
        if str(entity.get("source") or "").lower() == "proxy":
            location_status = "proxy"
            entity["requires_human_confirmation"] = True
        point_display: Optional[Point] = None
        point_metric: Optional[Point] = None
        feature_geometry = None
        if geometry_payload:
            point_display = shape(geometry_payload)
            if point_display.is_empty or point_display.geom_type != "Point":
                point_display = None
                location_status = "unresolved"
            else:
                source_crs = str(entity.get("geometry_crs") or config.display_crs)
                point_metric = _transform(point_display, _transformer(source_crs, config.metric_crs))
                point_display = _transform(point_metric, to_display)
        if display_geometry_payload:
            display_geometry = shape(display_geometry_payload)
            if not display_geometry.is_empty:
                source_crs = str(entity.get("geometry_crs") or config.display_crs)
                display_geometry = _transform(display_geometry, _transformer(source_crs, config.display_crs))
                feature_geometry = mapping(display_geometry)
        nearest_road_id, snap_metric, distance_m = (
            _nearest_road(point_metric, roads) if point_metric is not None else (None, None, None)
        )
        inside_boundary = (
            bool(boundary_metric.contains(point_metric) or boundary_metric.touches(point_metric))
            if boundary_metric is not None and point_metric is not None
            else None
        )
        confidence = round(float(entity.get("confidence") or 0.0), 3)
        requires_review = (
            bool(entity.get("requires_human_confirmation"))
            or location_status != "confirmed"
            or confidence < config.low_confidence_threshold
            or inside_boundary is False
        )
        spatial_reference_type = entity.get("spatial_reference_type")
        if not spatial_reference_type and point_display is not None:
            spatial_reference_type = "point"
        properties = {
            "entity_id": str(entity.get("entity_id") or f"ENT-{ordinal:04d}"),
            "name": str(entity.get("name") or ""),
            "entity_type": str(entity.get("entity_type") or "unknown"),
            "location_status": location_status,
            "confidence": confidence,
            "source": str(entity.get("source") or "unresolved"),
            "source_path": entity.get("source_path"),
            "location_resolver_source": entity.get("location_resolver_source"),
            "candidate_count": len(candidates),
            "inside_village_boundary": inside_boundary,
            "distance_to_current_road_m": round(distance_m, 3) if distance_m is not None else None,
            "nearest_road_id": nearest_road_id,
            "road_service_status": _status(distance_m, config),
            "requires_human_confirmation": requires_review,
            "source_chunk_ids": _string_list(entity.get("source_chunk_ids")),
            "source_intent_ids": _string_list(entity.get("source_intent_ids")),
            "source_intent_roles": _intent_role_list(entity.get("intent_roles")),
            "evidence_texts": _string_list(entity.get("evidence_texts")),
            "priority": str(entity.get("priority") or "medium"),
            "origin": entity.get("origin"),
            "candidate_summaries": entity.get("candidate_summaries", []),
            "spatial_reference_type": spatial_reference_type,
            "candidate_bsm_list": _string_list(entity.get("candidate_bsm_list")),
            "candidate_bbox": entity.get("candidate_bbox"),
            "bundle_geometry_summaries": entity.get("bundle_geometry_summaries", []),
            "source_geometry_type": entity.get("source_geometry_type")
            or ("Point" if point_display is not None else None),
            "kg_entity_id": entity.get("kg_entity_id"),
            "spatial_context": entity.get("spatial_context") or {},
            "bundle_spatial_context": entity.get("bundle_spatial_context") or {},
            "access_point_generation_method": entity.get("access_point_generation_method") or (
                "source_point" if point_display is not None else None
            ),
        }
        context_type = _context_entity_type(properties["spatial_context"])
        if context_type == "road" or str(properties.get("source_geometry_type") or "").lower() in {
            "linestring",
            "multilinestring",
        }:
            properties["entity_type"] = "road"
        elif context_type in {
            "farmland",
            "cultivated_land",
            "water",
            "ecological",
            "ecological_protection",
            "protected_farmland",
            "basic_farmland",
        }:
            properties["entity_type"] = context_type
        located.append(
            {
                "type": "Feature",
                "id": properties["entity_id"],
                "geometry": feature_geometry
                if feature_geometry is not None
                else mapping(point_display)
                if point_display is not None
                else None,
                "properties": properties,
                "_metric_geometry": point_metric,
                "_snap_metric": snap_metric,
            }
        )
    return located


def _cluster_entities(
    located: Sequence[Dict[str, Any]],
    config: PlanningNodeBuildConfig,
) -> List[List[Dict[str, Any]]]:
    usable = [
        feature
        for feature in located
        if feature.get("_metric_geometry") is not None
        and (feature.get("properties") or {}).get("location_status") == "confirmed"
        and (feature.get("properties") or {}).get("source") != "proxy"
    ]
    graph: Dict[int, List[int]] = defaultdict(list)
    for left_index, left in enumerate(usable):
        left_point = left["_metric_geometry"]
        for right_index in range(left_index + 1, len(usable)):
            right = usable[right_index]
            left_type = _node_type(
                str((left.get("properties") or {}).get("entity_type") or ""),
                str((left.get("properties") or {}).get("name") or ""),
            )
            right_type = _node_type(
                str((right.get("properties") or {}).get("entity_type") or ""),
                str((right.get("properties") or {}).get("name") or ""),
            )
            if left_type != right_type:
                duplicate_access_distance_m = min(25.0, config.cluster_distance_m / 4.0)
                if left_point.distance(right["_metric_geometry"]) > duplicate_access_distance_m:
                    continue
            if left_point.distance(right["_metric_geometry"]) <= config.cluster_distance_m:
                graph[left_index].append(right_index)
                graph[right_index].append(left_index)
    seen: set[int] = set()
    clusters: List[List[Dict[str, Any]]] = []
    for index in range(len(usable)):
        if index in seen:
            continue
        component: List[int] = []
        queue: deque[int] = deque([index])
        seen.add(index)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in graph.get(current, []):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        clusters.append([usable[item] for item in component])
    return clusters


def _planning_nodes(
    located: Sequence[Dict[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    roads: gpd.GeoDataFrame,
    config: PlanningNodeBuildConfig,
) -> List[Dict[str, Any]]:
    intents_by_id = {str(intent.get("intent_id")): intent for intent in intents}
    to_display = _transformer(config.metric_crs, config.display_crs)
    nodes: List[Dict[str, Any]] = []
    for index, cluster in enumerate(_cluster_entities(located, config), start=1):
        points = [feature["_metric_geometry"] for feature in cluster]
        center_metric = MultiPoint(points).centroid if len(points) > 1 else points[0]
        center_display = _transform(center_metric, to_display)
        source_entity_ids = [
            str((feature.get("properties") or {}).get("entity_id")) for feature in cluster
        ]
        source_intent_ids = sorted(
            {
                intent_id
                for feature in cluster
                for intent_id in _string_list((feature.get("properties") or {}).get("source_intent_ids"))
            }
        )
        source_intent_roles = sorted(
            {
                (role["intent_id"], role["role"])
                for feature in cluster
                for role in _intent_role_list((feature.get("properties") or {}).get("source_intent_roles"))
            }
        )
        source_chunk_ids = sorted(
            {
                chunk_id
                for feature in cluster
                for chunk_id in _string_list((feature.get("properties") or {}).get("source_chunk_ids"))
            }
        )
        names = [str((feature.get("properties") or {}).get("name") or "") for feature in cluster]
        entity_types = [
            str((feature.get("properties") or {}).get("entity_type") or "") for feature in cluster
        ]
        source_bsms = sorted(
            {
                bsm
                for feature in cluster
                for bsm in _string_list((feature.get("properties") or {}).get("candidate_bsm_list"))
            }
        )
        source_spatial_reference_types = sorted(
            {
                str((feature.get("properties") or {}).get("spatial_reference_type") or "")
                for feature in cluster
                if (feature.get("properties") or {}).get("spatial_reference_type")
            }
        )
        access_methods = sorted(
            {
                str((feature.get("properties") or {}).get("access_point_generation_method") or "")
                for feature in cluster
                if (feature.get("properties") or {}).get("access_point_generation_method")
            }
        )
        source_geometry_types = sorted(
            {
                str((feature.get("properties") or {}).get("source_geometry_type") or "")
                for feature in cluster
                if (feature.get("properties") or {}).get("source_geometry_type")
            }
        )
        source_road_relations = sorted(
            {
                relation
                for feature in cluster
                for relation in [_context_road_relation((feature.get("properties") or {}).get("spatial_context"))]
                if relation
            }
        )
        source_construction_permissions = sorted(
            {
                permission
                for feature in cluster
                for permission in [
                    _context_construction_permission(
                        (feature.get("properties") or {}).get("spatial_context")
                    )
                ]
                if permission
            }
        )
        source_planning_zones = sorted(
            {
                zone
                for feature in cluster
                for zone in [
                    _context_planning_zone((feature.get("properties") or {}).get("spatial_context"))
                ]
                if zone
            }
        )
        restricted_reference_reasons = sorted(
            {
                reason
                for feature in cluster
                for reason in _restricted_reference_reasons(feature.get("properties") or {})
            }
        )
        has_existing_road_reference = any(
            _is_existing_road_reference(feature.get("properties") or {}) for feature in cluster
        )
        has_restricted_reference = bool(restricted_reference_reasons)
        node_type_counts = Counter(_node_type(kind, name) for kind, name in zip(entity_types, names))
        node_type = node_type_counts.most_common(1)[0][0]
        if has_existing_road_reference:
            node_type = "road_access_node"
        elif has_restricted_reference:
            node_type = "unresolved_node"
        nearest_road_id, _, distance_m = _nearest_road(center_metric, roads)
        status = _status(distance_m, config)
        priorities = [str((feature.get("properties") or {}).get("priority") or "medium") for feature in cluster]
        priority = max(priorities, key=_priority_rank)
        confidence = round(
            min(float((feature.get("properties") or {}).get("confidence") or 0.0) for feature in cluster),
            3,
        )
        related_actions = {
            str(intents_by_id.get(intent_id, {}).get("action") or "")
            for intent_id in source_intent_ids
        }
        related_actions.discard("")
        recommended_action = "none"
        if confidence < config.low_confidence_threshold:
            recommended_action = "manual_review"
        elif has_restricted_reference:
            recommended_action = "manual_review"
        elif has_existing_road_reference and related_actions & {"widen", "harden", "repair"}:
            recommended_action = sorted(related_actions & {"widen", "harden", "repair"})[0]
        elif has_existing_road_reference:
            recommended_action = "manual_review"
        elif related_actions & {"widen", "harden", "repair"}:
            recommended_action = sorted(related_actions & {"widen", "harden", "repair"})[0]
        elif status == "isolated" and (distance_m or 0) >= config.min_new_connection_distance_m:
            recommended_action = "new" if priority != "low" or len(cluster) > 1 else "manual_review"
        elif status == "unresolved":
            recommended_action = "manual_review"
        requires_review = (
            recommended_action == "manual_review"
            or has_restricted_reference
            or any((feature.get("properties") or {}).get("requires_human_confirmation") for feature in cluster)
        )
        properties = {
            "planning_node_id": f"PN-{index:04d}",
            "node_type": node_type,
            "name": " / ".join(sorted(set(filter(None, names)))[:4]),
            "source_entity_ids": source_entity_ids,
            "source_intent_ids": source_intent_ids,
            "source_intent_roles": [
                {"intent_id": intent_id, "role": role} for intent_id, role in source_intent_roles
            ],
            "source_chunk_ids": source_chunk_ids,
            "source_bsm_list": source_bsms,
            "source_spatial_reference_types": source_spatial_reference_types,
            "source_geometry_types": source_geometry_types,
            "source_road_relations": source_road_relations,
            "existing_road_reference": has_existing_road_reference,
            "restricted_spatial_reference": has_restricted_reference,
            "restricted_reference_reasons": restricted_reference_reasons,
            "source_construction_permissions": source_construction_permissions,
            "source_planning_zones": source_planning_zones,
            "access_point_generation_method": " / ".join(access_methods) if access_methods else "source_point",
            "service_weight": round(
                0.0
                if has_restricted_reference
                else len(cluster) * {"high": 1.5, "medium": 1.0, "low": 0.6}.get(priority, 1.0),
                3,
            ),
            "priority": priority,
            "road_service_status": status,
            "nearest_road_id": nearest_road_id,
            "distance_to_current_road_m": round(distance_m, 3) if distance_m is not None else None,
            "recommended_action": recommended_action,
            "confidence": confidence,
            "requires_human_confirmation": requires_review,
        }
        nodes.append(
            {
                "type": "Feature",
                "id": properties["planning_node_id"],
                "geometry": mapping(center_display),
                "properties": properties,
            }
        )
    unresolved_index = len(nodes) + 1
    for feature in located:
        props = feature.get("properties") or {}
        if props.get("location_status") == "confirmed" and props.get("source") != "proxy":
            continue
        properties = {
            "planning_node_id": f"PN-{unresolved_index:04d}",
            "node_type": "unresolved_node",
            "name": props.get("name"),
            "source_entity_ids": [props.get("entity_id")],
            "source_intent_ids": _string_list(props.get("source_intent_ids")),
            "source_intent_roles": _intent_role_list(props.get("source_intent_roles")),
            "source_chunk_ids": _string_list(props.get("source_chunk_ids")),
            "source_bsm_list": _string_list(props.get("candidate_bsm_list")),
            "source_spatial_reference_types": _string_list(props.get("spatial_reference_type")),
            "source_geometry_types": _string_list(props.get("source_geometry_type")),
            "source_road_relations": _string_list(_context_road_relation(props.get("spatial_context"))),
            "existing_road_reference": _is_existing_road_reference(props),
            "restricted_spatial_reference": _is_restricted_spatial_reference(props),
            "restricted_reference_reasons": _restricted_reference_reasons(props),
            "source_construction_permissions": _string_list(
                _context_construction_permission(props.get("spatial_context"))
            ),
            "source_planning_zones": _string_list(_context_planning_zone(props.get("spatial_context"))),
            "access_point_generation_method": props.get("access_point_generation_method"),
            "service_weight": 0.0,
            "priority": props.get("priority") or "medium",
            "road_service_status": "unresolved",
            "nearest_road_id": None,
            "distance_to_current_road_m": None,
            "recommended_action": "manual_review",
            "confidence": props.get("confidence"),
            "requires_human_confirmation": True,
        }
        nodes.append(
            {
                "type": "Feature",
                "id": properties["planning_node_id"],
                "geometry": feature.get("geometry"),
                "properties": properties,
            }
        )
        unresolved_index += 1
    return nodes


def _road_planning_requests(
    nodes: Sequence[Dict[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    config: PlanningNodeBuildConfig,
) -> List[Dict[str, Any]]:
    requests: List[Dict[str, Any]] = []
    intent_by_node: Dict[str, set[str]] = defaultdict(set)
    nodes_by_intent_role: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    intents_by_id = {str(intent.get("intent_id")): intent for intent in intents}
    for node in nodes:
        props = node.get("properties") or {}
        node_id = str(props.get("planning_node_id"))
        for intent_id in _string_list(props.get("source_intent_ids")):
            intent = intents_by_id.get(intent_id)
            if intent:
                intent_by_node[node_id].add(intent_id)
        for role in _intent_role_list(props.get("source_intent_roles")):
            nodes_by_intent_role[role["intent_id"]][role["role"]].append(node)

    def _role_node(candidates: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                str((item.get("properties") or {}).get("node_type") or "") == "unresolved_node",
                bool((item.get("properties") or {}).get("requires_human_confirmation")),
                -float((item.get("properties") or {}).get("confidence") or 0.0),
            ),
        )[0]

    def _node_request_type(action: str, props: Mapping[str, Any]) -> str:
        if action == "manual_review":
            return "verify_existing"
        return REQUEST_BY_ACTION.get(action, "verify_existing")

    request_index = 1
    paired_node_ids: set[str] = set()
    for intent in intents:
        intent_id = str(intent.get("intent_id") or "")
        if not intent_id:
            continue
        action = str(intent.get("action") or "new")
        target_id = str(intent.get("target_id") or "")
        start_node = _role_node(nodes_by_intent_role.get(intent_id, {}).get("start", []))
        end_node = _role_node(nodes_by_intent_role.get(intent_id, {}).get("end", []))
        if not start_node or not end_node:
            continue
        start_props = start_node.get("properties") or {}
        end_props = end_node.get("properties") or {}
        start_id = str(start_props.get("planning_node_id") or "")
        end_id = str(end_props.get("planning_node_id") or "")
        if not start_id or not end_id or start_id == end_id:
            continue
        endpoint_props = (start_props, end_props)
        has_restricted = any(props.get("restricted_spatial_reference") for props in endpoint_props)
        existing_count = sum(1 for props in endpoint_props if props.get("existing_road_reference"))
        has_unresolved_endpoint = any(
            str(props.get("node_type") or "") == "unresolved_node" for props in endpoint_props
        )
        requires_review = (
            bool(intent.get("requires_human_confirmation"))
            or any(props.get("requires_human_confirmation") for props in endpoint_props)
            or has_restricted
            or existing_count == 2
            or (existing_count > 0 and has_unresolved_endpoint)
        )
        if has_restricted or existing_count == 2 or (existing_count > 0 and has_unresolved_endpoint):
            request_type = "verify_existing"
        else:
            request_type = REQUEST_BY_ACTION.get(action, "verify_existing")
        node_type = str(start_props.get("node_type") or end_props.get("node_type") or "facility_node")
        source_bsms = sorted(
            {
                bsm
                for props in endpoint_props
                for bsm in _string_list(props.get("source_bsm_list"))
            }
        )
        reason = (
            "Text intent endpoint is a protected, restricted, water, farmland, or no-construction entity; confirm the constraint before route generation."
            if has_restricted
            else "Text intent includes an existing road reference without a confirmed service endpoint; verify or convert the intent to an upgrade task instead of creating a new road."
            if existing_count > 0 and has_unresolved_endpoint
            else "Text intent endpoints both resolve to existing road references; verify or convert the intent to an upgrade task instead of creating a new road."
            if existing_count == 2
            else "Text intent connects start_place to end_place; this request preserves the planning-node pair before Stage 4 route geometry generation."
        )
        requests.append(
            {
                "request_id": f"RPR-{request_index:04d}",
                "request_type": request_type,
                "priority": max(
                    [str(props.get("priority") or "medium") for props in endpoint_props],
                    key=_priority_rank,
                ),
                "start_node_id": start_id,
                "end_node_id": end_id,
                "served_node_ids": sorted({start_id, end_id}),
                "related_intent_ids": [intent_id],
                "target_id": target_id,
                "target_ids": [target_id] if target_id else [],
                "source_bsm_list": source_bsms,
                "recommended_road_class": intent.get("recommended_road_class") or "village_road",
                "recommended_width_m": intent.get("recommended_width_m")
                or _recommended_width(action, node_type),
                "avoid_constraints": _as_list(intent.get("constraints")),
                "allow_reuse_existing": True,
                "requires_human_confirmation": requires_review,
                "reason": reason,
            }
        )
        paired_node_ids.update({start_id, end_id})
        request_index += 1

    for node in nodes:
        props = node.get("properties") or {}
        node_id = str(props.get("planning_node_id"))
        if node_id in paired_node_ids:
            continue
        action = str(props.get("recommended_action") or "manual_review")
        if action == "none":
            continue
        request_type = _node_request_type(action, props)
        road_ref = f"nearest_road:{props.get('nearest_road_id')}" if props.get("nearest_road_id") else None
        requires_review = bool(props.get("requires_human_confirmation")) or action == "manual_review"
        related_intents = sorted(intent_by_node.get(node_id, set()))
        target_ids = sorted({
            str(intents_by_id[intent_id].get("target_id") or "")
            for intent_id in related_intents
            if intent_id in intents_by_id
            and str(intents_by_id[intent_id].get("target_id") or "")
        })
        node_type = str(props.get("node_type") or "facility_node")
        requests.append(
            {
                "request_id": f"RPR-{request_index:04d}",
                "request_type": request_type,
                "priority": props.get("priority") or "medium",
                "start_node_id": node_id,
                "end_node_id": road_ref,
                "served_node_ids": [node_id],
                "related_intent_ids": related_intents,
                "target_id": target_ids[0] if len(target_ids) == 1 else "",
                "target_ids": target_ids,
                "source_bsm_list": props.get("source_bsm_list") or [],
                "recommended_road_class": "village_road",
                "recommended_width_m": _recommended_width(action, node_type),
                "avoid_constraints": [],
                "allow_reuse_existing": action != "new" or props.get("road_service_status") == "near_network",
                "requires_human_confirmation": requires_review,
                "reason": (
                    "Node is isolated from the current road network and should be considered for a new access request."
                    if action == "new"
                    else "KG or bundle context marks this target as protected, restricted, water, farmland, or no-construction land; confirm whether it is a constraint instead of a road service node."
                    if props.get("restricted_spatial_reference")
                    else "KG or bundle geometry indicates this target is an existing road reference; verify or upgrade the existing segment instead of creating a new road."
                    if props.get("existing_road_reference")
                    else "Node or related intent needs manual verification before route geometry is generated."
                    if action == "manual_review"
                    else f"Related text intent requests existing-road {action} work."
                ),
            }
        )
        request_index += 1
    return requests


def _review_queue(
    located: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
    requests: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for feature in located:
        props = feature.get("properties") or {}
        if not props.get("requires_human_confirmation"):
            continue
        items.append(
            {
                "review_id": f"HR-E-{len(items) + 1:04d}",
                "review_type": "entity_location",
                "target_id": props.get("entity_id"),
                "name": props.get("name"),
                "reason": (
                    "multiple_candidates"
                    if props.get("location_status") == "candidate"
                    else "unresolved_or_low_confidence_location"
                ),
                "location_status": props.get("location_status"),
                "confidence": props.get("confidence"),
                "candidate_count": props.get("candidate_count"),
                "spatial_reference_type": props.get("spatial_reference_type"),
                "candidate_bsm_list": props.get("candidate_bsm_list"),
                "candidate_bbox": props.get("candidate_bbox"),
                "bundle_geometry_summaries": props.get("bundle_geometry_summaries"),
                "restricted_reference_reasons": _restricted_reference_reasons(props),
                "source_chunk_ids": props.get("source_chunk_ids"),
                "evidence_texts": props.get("evidence_texts"),
            }
        )
    for node in nodes:
        props = node.get("properties") or {}
        if not props.get("requires_human_confirmation"):
            continue
        items.append(
            {
                "review_id": f"HR-N-{len(items) + 1:04d}",
                "review_type": "planning_node",
                "target_id": props.get("planning_node_id"),
                "name": props.get("name"),
                "reason": props.get("recommended_action"),
                "road_service_status": props.get("road_service_status"),
                "confidence": props.get("confidence"),
                "source_entity_ids": props.get("source_entity_ids"),
                "source_intent_ids": props.get("source_intent_ids"),
                "source_intent_roles": props.get("source_intent_roles"),
                "source_bsm_list": props.get("source_bsm_list"),
                "source_spatial_reference_types": props.get("source_spatial_reference_types"),
                "restricted_spatial_reference": props.get("restricted_spatial_reference"),
                "restricted_reference_reasons": props.get("restricted_reference_reasons"),
            }
        )
    for request in requests:
        if not request.get("requires_human_confirmation"):
            continue
        items.append(
            {
                "review_id": f"HR-R-{len(items) + 1:04d}",
                "review_type": "road_planning_request",
                "target_id": request.get("request_id"),
                "reason": request.get("reason"),
                "request_type": request.get("request_type"),
                "served_node_ids": request.get("served_node_ids"),
                "related_intent_ids": request.get("related_intent_ids"),
            }
        )
    return {
        "type": "HumanReviewQueue",
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "review_count": len(items),
    }


def _human_confirmation_template(
    review: Mapping[str, Any],
    located: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    entity_by_id = {
        str((feature.get("properties") or {}).get("entity_id")): feature.get("properties") or {}
        for feature in located
    }
    node_by_id = {
        str((feature.get("properties") or {}).get("planning_node_id")): feature.get("properties") or {}
        for feature in nodes
    }
    confirmations: List[Dict[str, Any]] = []
    for item in review.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        review_type = str(item.get("review_type") or "")
        target_id = str(item.get("target_id") or "")
        source_props: Mapping[str, Any] = {}
        if review_type == "entity_location":
            source_props = entity_by_id.get(target_id, {})
        elif review_type == "planning_node":
            source_props = node_by_id.get(target_id, {})
        elif review_type == "road_planning_request":
            continue
        confirmations.append(
            {
                "review_id": item.get("review_id"),
                "review_type": review_type,
                "target_id": target_id,
                "name": item.get("name") or source_props.get("name"),
                "confirmation_status": "pending",
                "confidence": None,
                "bsm_list": item.get("candidate_bsm_list")
                or item.get("source_bsm_list")
                or source_props.get("candidate_bsm_list")
                or source_props.get("source_bsm_list")
                or [],
                "geometry": None,
                "candidate_bbox": item.get("candidate_bbox") or source_props.get("candidate_bbox"),
                "spatial_context": source_props.get("spatial_context")
                or {
                    "planning_zone": None,
                    "construction_permission": None,
                    "entity_type": None,
                    "road_relation": None,
                },
                "source_entity_ids": item.get("source_entity_ids") or source_props.get("source_entity_ids") or [],
                "source_intent_ids": item.get("source_intent_ids") or source_props.get("source_intent_ids") or [],
                "source_chunk_ids": item.get("source_chunk_ids") or source_props.get("source_chunk_ids") or [],
                "evidence_texts": item.get("evidence_texts") or source_props.get("evidence_texts") or [],
                "review_reason": item.get("reason"),
                "instructions": (
                    "Set confirmation_status to confirmed/candidate/unresolved. For confirmed items, provide "
                    "bsm_list or geometry. Bbox-only answers remain candidate and will be sent back for KG/manual refinement."
                ),
            }
        )
    return {
        "type": "RoadHumanConfirmationTemplate",
        "schema_version": SCHEMA_VERSION,
        "stage": "2.6",
        "confirmation_count": len(confirmations),
        "confirmations": confirmations,
        "can_be_used_as_manual_confirmation_path_after_editing": True,
        "accepted_confirmation_statuses": ["confirmed", "candidate", "unresolved"],
    }


def _quality_gate_reason(props: Mapping[str, Any], entity_props: Sequence[Mapping[str, Any]]) -> List[str]:
    reasons: List[str] = []
    try:
        confidence_value = float(props.get("confidence"))
    except (TypeError, ValueError):
        confidence_value = 0.0
    if confidence_value < 0.65:
        reasons.append("low_confidence")
    if props.get("node_type") == "unresolved_node":
        reasons.append("unresolved_node")
    if props.get("restricted_spatial_reference"):
        reasons.append("restricted_spatial_reference")
    if props.get("existing_road_reference"):
        reasons.append("existing_road_reference")
    if props.get("road_service_status") == "unresolved":
        reasons.append("unresolved_road_service_status")
    if props.get("requires_human_confirmation"):
        reasons.append("requires_human_confirmation")
    entity_statuses = {
        str(item.get("location_status") or "unknown") for item in entity_props if item
    }
    if entity_statuses & {"candidate", "proxy", "unresolved"}:
        reasons.append("unconfirmed_source_entity")
    if any(item.get("candidate_bbox") for item in entity_props):
        reasons.append("bbox_requires_refinement")
    return sorted(set(reasons))


def _quality_gate_next_action(
    props: Mapping[str, Any],
    reasons: Sequence[str],
    retry_target_ids: set[str],
) -> str:
    entity_ids = set(_string_list(props.get("source_entity_ids")))
    if entity_ids & retry_target_ids or "bbox_requires_refinement" in reasons:
        return "query_kg_for_bsm_or_ranked_candidates"
    if props.get("restricted_spatial_reference"):
        return "confirm_constraint_or_replace_with_service_entity"
    if props.get("existing_road_reference"):
        return "verify_existing_road_or_convert_to_upgrade_intent"
    if "unresolved_node" in reasons or "unconfirmed_source_entity" in reasons:
        return "manual_or_kg_location_confirmation"
    if "low_confidence" in reasons:
        return "raise_confidence_with_additional_source"
    if "requires_human_confirmation" in reasons:
        return "manual_review_clear_blocking_reasons"
    if props.get("recommended_action") == "none":
        return "no_route_generation_needed"
    if reasons:
        return "manual_review_clear_blocking_reasons"
    return "ready_for_stage3_stage4"


def _spatial_quality_gates(
    located: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
    requests: Sequence[Mapping[str, Any]],
    iteration_records: Mapping[str, Any],
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    entity_by_id = {
        str((feature.get("properties") or {}).get("entity_id")): feature.get("properties") or {}
        for feature in located
    }
    request_by_node: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for request in requests:
        for node_id in _string_list(request.get("served_node_ids")):
            request_by_node[node_id].append(request)
    retry_target_ids = {
        str(item.get("target_id"))
        for item in iteration_records.get("retry_queue") or []
        if str(item.get("target_id") or "").strip()
    }
    node_items: List[Dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    next_action_counts: Counter[str] = Counter()
    for node in nodes:
        props = node.get("properties") or {}
        node_id = str(props.get("planning_node_id") or "")
        source_entity_ids = _string_list(props.get("source_entity_ids"))
        entity_props = [entity_by_id.get(entity_id, {}) for entity_id in source_entity_ids]
        reasons = _quality_gate_reason(props, entity_props)
        action = str(props.get("recommended_action") or "manual_review")
        related_requests = request_by_node.get(node_id, [])
        request_types = sorted({str(item.get("request_type") or "") for item in related_requests if item})
        if action == "none" and not reasons:
            gate_status = "not_needed"
        elif not reasons and action in {"new", "widen", "harden", "repair"}:
            gate_status = "pass"
        elif props.get("restricted_spatial_reference"):
            gate_status = "blocked_constraint"
        elif set(source_entity_ids) & retry_target_ids or "bbox_requires_refinement" in reasons:
            gate_status = "needs_kg_retry"
        else:
            gate_status = "needs_review"
        next_action = _quality_gate_next_action(props, reasons, retry_target_ids)
        status_counts[gate_status] += 1
        next_action_counts[next_action] += 1
        node_items.append(
            {
                "planning_node_id": node_id,
                "gate_status": gate_status,
                "recommended_action": action,
                "request_types": request_types,
                "blocking_reasons": reasons,
                "next_action": next_action,
                "confidence": props.get("confidence"),
                "priority": props.get("priority"),
                "road_service_status": props.get("road_service_status"),
                "source_entity_ids": source_entity_ids,
                "source_intent_ids": _string_list(props.get("source_intent_ids")),
                "source_intent_roles": _intent_role_list(props.get("source_intent_roles")),
                "source_chunk_ids": _string_list(props.get("source_chunk_ids")),
                "source_bsm_list": _string_list(props.get("source_bsm_list")),
                "restricted_reference_reasons": props.get("restricted_reference_reasons") or [],
                "existing_road_reference": bool(props.get("existing_road_reference")),
                "requires_human_confirmation": bool(props.get("requires_human_confirmation")),
            }
        )
    route_request_count = sum(
        1 for item in node_items if item["recommended_action"] in {"new", "widen", "harden", "repair"}
    )
    return {
        "type": "RoadSpatialQualityGateCollection",
        "schema_version": SCHEMA_VERSION,
        "stage": "2.6",
        "automatic_route_generation_allowed": bool(
            (report.get("planning_gate") or {}).get("automatic_route_generation_allowed")
        ),
        "gate_policy": (
            "Stage 3/4 automatic route generation is allowed only when all planning nodes "
            "and source entities pass review gates."
        ),
        "summary": {
            "node_count": len(node_items),
            "route_request_node_count": route_request_count,
            "pass_count": status_counts.get("pass", 0),
            "status_counts": dict(sorted(status_counts.items())),
            "next_action_counts": dict(sorted(next_action_counts.items())),
            "kg_retry_target_count": len(retry_target_ids),
            "human_review_count": report.get("human_review_count"),
        },
        "nodes": node_items,
    }


def _constraint_target_layer(props: Mapping[str, Any]) -> str:
    context = props.get("spatial_context") or {}
    values = [
        _context_planning_zone(context),
        _context_value(context, "landuse", "landuse_type", "land_type"),
        _context_entity_type(context),
        props.get("entity_type"),
    ]
    normalized = {_normalise_context_code(value) for value in values if value}
    if normalized & {"water", "waterbody", "\u6c34\u57df"}:
        return "water"
    if normalized & {"ecological", "ecology", "ecologicalprotection", "\u751f\u6001\u4fdd\u62a4\u533a"}:
        return "ecological_protection"
    if normalized & {
        "farmland",
        "cultivatedland",
        "farmlandprotection",
        "permanentbasicfarmland",
        "protectedfarmland",
        "basicfarmland",
        "\u8015\u5730",
        "\u519c\u7530\u4fdd\u62a4\u533a",
    }:
        return "farmland_protection"
    return "restricted_planning_entity"


def _derived_constraints_from_restricted_entities(
    located: Sequence[Dict[str, Any]],
    display_crs: str,
) -> List[Dict[str, Any]]:
    constraints: List[Dict[str, Any]] = []
    for feature in located:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if not geometry or not _is_restricted_spatial_reference(props):
            continue
        constraints.append(
            {
                "constraint_id": f"S26-C-{len(constraints) + 1:04d}",
                "constraint_type": "avoid",
                "target_layer": _constraint_target_layer(props),
                "severity": "hard",
                "buffer_m": 0.0,
                "geometry": geometry,
                "geometry_crs": display_crs,
                "source_paths": [props.get("source_path")] if props.get("source_path") else [],
                "source_entity_ids": [props.get("entity_id")],
                "source_bsm_list": props.get("candidate_bsm_list") or [],
                "restricted_reference_reasons": _restricted_reference_reasons(props),
                "evidence": {
                    "evidence_id": props.get("entity_id"),
                    "source_chunk_ids": props.get("source_chunk_ids") or [],
                    "evidence_texts": props.get("evidence_texts") or [],
                },
                "derived_from": "stage2_6_restricted_planning_entity",
                "requires_human_confirmation": bool(props.get("requires_human_confirmation")),
            }
        )
    return constraints


def _merge_constraints_payload(
    base_payload: Mapping[str, Any],
    derived_constraints: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    payload = json.loads(json.dumps(base_payload, ensure_ascii=False))
    existing = [item for item in payload.get("constraints") or [] if isinstance(item, Mapping)]
    seen = {str(item.get("constraint_id")) for item in existing}
    merged = list(existing)
    for item in derived_constraints:
        constraint_id = str(item.get("constraint_id") or "")
        if constraint_id and constraint_id not in seen:
            merged.append(dict(item))
            seen.add(constraint_id)
    payload["constraints"] = merged
    payload["stage2_6_derived_constraint_count"] = len(derived_constraints)
    return payload


def _entity_retry_action(props: Mapping[str, Any]) -> str:
    status = str(props.get("location_status") or "")
    spatial_reference_type = str(props.get("spatial_reference_type") or "")
    if status == "unresolved":
        return "query_kg_for_entity_bsm_or_bbox"
    if status == "candidate" and spatial_reference_type == "bbox":
        return "refine_bbox_to_bsm_candidates"
    if status == "candidate":
        return "disambiguate_multiple_spatial_candidates"
    if props.get("inside_village_boundary") is False:
        return "verify_boundary_or_entity_match"
    if float(props.get("confidence") or 0.0) < 0.65:
        return "raise_confidence_with_additional_source"
    return "accepted"


def _iteration_records(
    intents: Sequence[Mapping[str, Any]],
    entities: Sequence[Mapping[str, Any]],
    spatial_candidates: Sequence[Mapping[str, Any]],
    located: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
    requests: Sequence[Mapping[str, Any]],
    review: Mapping[str, Any],
) -> Dict[str, Any]:
    retry_items: List[Dict[str, Any]] = []
    accepted_entities = 0
    for feature in located:
        props = feature.get("properties") or {}
        action = _entity_retry_action(props)
        if action == "accepted":
            accepted_entities += 1
            continue
        retry_items.append(
            {
                "target_id": props.get("entity_id"),
                "name": props.get("name"),
                "current_status": props.get("location_status"),
                "spatial_reference_type": props.get("spatial_reference_type"),
                "candidate_bsm_list": props.get("candidate_bsm_list"),
                "candidate_bbox": props.get("candidate_bbox"),
                "confidence": props.get("confidence"),
                "next_action": action,
                "query_contract": {
                    "input": {
                        "name": props.get("name"),
                        "entity_type": props.get("entity_type"),
                        "source_chunk_ids": props.get("source_chunk_ids"),
                        "evidence_texts": props.get("evidence_texts"),
                    },
                    "expected_output": "entity_id, confidence, spatial_context, bsm_list or candidate_bbox",
                },
            }
        )

    blocked_requests = [
        {
            "request_id": request.get("request_id"),
            "request_type": request.get("request_type"),
            "served_node_ids": request.get("served_node_ids"),
            "reason": request.get("reason"),
        }
        for request in requests
        if request.get("requires_human_confirmation")
    ]
    return {
        "type": "RoadSpatialPreprocessingIterationRecords",
        "schema_version": SCHEMA_VERSION,
        "iterations": [
            {
                "iteration_id": "ITER-001",
                "worker": "parse_to_road_intents",
                "status": "completed",
                "input_count": len(intents),
                "output_count": len(intents),
                "evaluator_summary": "Road intents were normalised with evidence and source chunk references.",
            },
            {
                "iteration_id": "ITER-002",
                "worker": "kg_spatial_candidate_resolution",
                "status": "completed",
                "input_count": len(entities),
                "output_count": len(spatial_candidates),
                "evaluator_summary": "KG and Stage-2 spatial references were converted into point, BSM, bbox, or geometry candidates.",
            },
            {
                "iteration_id": "ITER-003",
                "worker": "bundle_geometry_lookup",
                "status": "completed",
                "input_count": len(spatial_candidates),
                "output_count": sum(
                    1
                    for candidate in spatial_candidates
                    if candidate.get("display_geometry") or candidate.get("geometry")
                ),
                "evaluator_summary": "BSM references were resolved against local bundle geometry sources where available.",
            },
            {
                "iteration_id": "ITER-004",
                "worker": "spatial_evaluator",
                "status": "needs_retry_or_review" if retry_items else "completed",
                "input_count": len(located),
                "accepted_entity_count": accepted_entities,
                "retry_item_count": len(retry_items),
                "blocked_request_count": len(blocked_requests),
                "evaluator_summary": (
                    "Some entities need KG retry or human confirmation before automatic route generation."
                    if retry_items or blocked_requests
                    else "All located entities passed the spatial preprocessing evaluator."
                ),
            },
        ],
        "retry_queue": retry_items,
        "blocked_requests": blocked_requests,
        "human_review_count": int(review.get("review_count") or 0),
    }


def _kg_retry_requests(
    iteration_records: Mapping[str, Any],
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    requests: List[Dict[str, Any]] = []
    for index, item in enumerate(iteration_records.get("retry_queue") or [], start=1):
        contract = item.get("query_contract") or {}
        contract_input = contract.get("input") or {}
        next_action = str(item.get("next_action") or "")
        preferred_resolution = "bsm_list"
        if next_action == "refine_bbox_to_bsm_candidates":
            preferred_resolution = "bsm_list_within_bbox"
        elif next_action == "disambiguate_multiple_spatial_candidates":
            preferred_resolution = "single_best_candidate_or_ranked_candidates"
        elif next_action == "verify_boundary_or_entity_match":
            preferred_resolution = "boundary_checked_entity_reference"
        requests.append(
            {
                "retry_request_id": f"KGR-{index:04d}",
                "target_id": item.get("target_id"),
                "name": item.get("name"),
                "current_status": item.get("current_status"),
                "next_action": next_action,
                "preferred_resolution": preferred_resolution,
                "query_input": {
                    "name": contract_input.get("name") or item.get("name"),
                    "entity_type": contract_input.get("entity_type"),
                    "source_chunk_ids": contract_input.get("source_chunk_ids") or [],
                    "evidence_texts": contract_input.get("evidence_texts") or [],
                    "candidate_bsm_list": item.get("candidate_bsm_list") or [],
                    "candidate_bbox": item.get("candidate_bbox"),
                    "confidence": item.get("confidence"),
                    "spatial_reference_type": item.get("spatial_reference_type"),
                },
                "expected_response_schema": {
                    "target_id": "same target_id as request",
                    "confirmation_status": "confirmed | candidate | unresolved",
                    "entity_id": "KG entity identifier when available",
                    "name": "canonical entity name",
                    "confidence": "0..1",
                    "spatial_context": {
                        "entity_type": "parcel | road | facility | settlement | zone | water | farmland | other",
                        "planning_zone": "optional planning zone",
                        "construction_permission": "allow_construction | forbid_construction | conditional | unknown",
                        "road_relation": "connected | near_network | isolated | road_crosses | road_segment | unknown",
                    },
                    "bsm_list": "preferred when exact bundle objects are known",
                    "geometry": "optional point/line/polygon GeoJSON geometry",
                    "candidate_bbox": "allowed only when exact BSM/geometry cannot be resolved",
                    "source": "knowledge_graph | manual | gazetteer",
                },
                "acceptance_rules": [
                    "Do not invent BSM or geometry.",
                    "Every returned object must include confidence and source.",
                    "Prefer exact BSM list over bbox.",
                    "If only bbox is returned, mark confirmation_status as candidate.",
                    "Existing road segment matches must set spatial_context.entity_type=road and road_relation=road_segment.",
                    "Existing road segment matches must not be converted into new_connection requests.",
                    "Protected, water, farmland, ecological, or forbid_construction entities must be treated as constraints or manual-review targets, not automatic road service nodes.",
                ],
            }
        )
    return {
        "type": "RoadKnowledgeGraphRetryRequestCollection",
        "schema_version": SCHEMA_VERSION,
        "stage": "2.6",
        "request_count": len(requests),
        "source_stage2_dir": report.get("input_stage2_dir"),
        "bundle_geometry_sources": report.get("bundle_geometry_sources") or [],
        "requests": requests,
        "response_can_be_used_as_manual_confirmation_path": True,
    }


def _execute_trace(
    report: Mapping[str, Any],
    iteration_records: Mapping[str, Any],
    kg_retry_requests: Mapping[str, Any],
    review: Mapping[str, Any],
) -> Dict[str, Any]:
    retry_queue = iteration_records.get("retry_queue") or []
    return {
        "type": "RoadSpatialPreprocessingTrace",
        "schema_version": SCHEMA_VERSION,
        "stage": "2.6",
        "pipeline": [
            "parse_road_intents",
            "resolve_kg_spatial_candidates",
            "lookup_bundle_geometry_by_bsm",
            "evaluate_spatial_reliability",
            "build_planning_nodes",
            "build_road_planning_requests",
        ],
        "gate": report.get("planning_gate"),
        "source_statistics": {
            "road_intent_count": report.get("road_intent_count"),
            "spatial_candidate_count": report.get("spatial_candidate_count"),
            "bundle_geometry_bsm_count": report.get("bundle_geometry_bsm_count"),
            "located_entity_count": report.get("located_entity_count"),
            "planning_node_count": report.get("planning_node_count"),
            "road_planning_request_count": report.get("road_planning_request_count"),
            "human_review_count": report.get("human_review_count"),
            "quality_gate_status_counts": report.get("quality_gate_status_counts"),
        },
        "next_actions": [
            "run_stage3_when_gate_allows_or_for_review_preview",
            "send_retry_queue_to_kg_adapter",
            "collect_manual_confirmations_for_low_confidence_items",
            "rerun_stage2_6_with_manual_confirmation_path",
        ]
        if retry_queue or int(review.get("review_count") or 0) > 0
        else ["run_stage3_stage4_stage5"],
        "retry_queue_count": len(retry_queue),
        "kg_retry_request_count": int(kg_retry_requests.get("request_count") or 0),
        "kg_retry_requests_path_hint": "kg_retry_requests.json",
        "review_queue_path_hint": "human_review_queue.json",
        "quality_gates_path_hint": "spatial_quality_gates.json",
    }


def _kg_updates(
    located: Sequence[Dict[str, Any]],
    nodes: Sequence[Dict[str, Any]],
    intents: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    triples: List[Dict[str, Any]] = []
    for intent in intents:
        intent_id = intent.get("intent_id")
        triples.append(
            {
                "subject": intent_id,
                "predicate": "has_action",
                "object": intent.get("action"),
                "source_chunk_id": intent.get("source_chunk_id"),
                "confidence": intent.get("confidence"),
            }
        )
        for place in intent.get("mentioned_places") or []:
            triples.append(
                {
                    "subject": intent_id,
                    "predicate": "mentions_place",
                    "object": place,
                    "source_chunk_id": intent.get("source_chunk_id"),
                    "confidence": intent.get("confidence"),
                }
            )
    for feature in located:
        props = feature.get("properties") or {}
        triples.append(
            {
                "subject": props.get("entity_id"),
                "predicate": "has_location_status",
                "object": props.get("location_status"),
                "source_chunk_ids": props.get("source_chunk_ids"),
                "confidence": props.get("confidence"),
            }
        )
        for bsm in props.get("candidate_bsm_list") or []:
            triples.append(
                {
                    "subject": props.get("entity_id"),
                    "predicate": "candidate_bsm",
                    "object": bsm,
                    "source_chunk_ids": props.get("source_chunk_ids"),
                    "confidence": props.get("confidence"),
                }
            )
    for node in nodes:
        props = node.get("properties") or {}
        for entity_id in props.get("source_entity_ids") or []:
            triples.append(
                {
                    "subject": props.get("planning_node_id"),
                    "predicate": "aggregates_entity",
                    "object": entity_id,
                    "confidence": props.get("confidence"),
                }
            )
        for bsm in props.get("source_bsm_list") or []:
            triples.append(
                {
                    "subject": props.get("planning_node_id"),
                    "predicate": "derived_from_bsm",
                    "object": bsm,
                    "confidence": props.get("confidence"),
                }
            )
    return {
        "type": "PlanningKnowledgeGraphUpdate",
        "schema_version": SCHEMA_VERSION,
        "triples": triples,
        "triple_count": len(triples),
    }


def _compatibility_demands(nodes: Sequence[Dict[str, Any]], display_crs: str) -> Dict[str, Any]:
    features: List[Dict[str, Any]] = []
    for node in nodes:
        props = node.get("properties") or {}
        if props.get("node_type") == "unresolved_node":
            continue
        if props.get("restricted_spatial_reference"):
            continue
        feature_props = {
            "demand_id": props.get("planning_node_id"),
            "planning_node_id": props.get("planning_node_id"),
            "name": props.get("name"),
            "place_name": props.get("name"),
            "demand_type": props.get("node_type"),
            "priority": props.get("priority"),
            "service_weight": props.get("service_weight"),
            "source_entity_ids": props.get("source_entity_ids"),
            "source_intent_ids": props.get("source_intent_ids"),
            "source_intent_roles": props.get("source_intent_roles"),
            "source_bsm_list": props.get("source_bsm_list"),
            "source_spatial_reference_types": props.get("source_spatial_reference_types"),
            "source_geometry_types": props.get("source_geometry_types"),
            "source_road_relations": props.get("source_road_relations"),
            "existing_road_reference": props.get("existing_road_reference"),
            "restricted_spatial_reference": props.get("restricted_spatial_reference"),
            "restricted_reference_reasons": props.get("restricted_reference_reasons"),
            "confidence": props.get("confidence"),
            "requires_human_confirmation": props.get("requires_human_confirmation"),
            "location_status": "resolved",
            "location_source": "stage2_6_planning_node",
        }
        features.append(
            {
                "type": "Feature",
                "id": props.get("planning_node_id"),
                "geometry": node.get("geometry"),
                "properties": feature_props,
            }
        )
    payload = _feature_collection("stage2_6_demand_points", display_crs, features)
    payload["data_mode"] = "production"
    payload["generated_from"] = "stage2_6_planning_nodes"
    return payload


def _compatibility_projects(requests: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    projects: List[Dict[str, Any]] = []
    for request in requests:
        if request.get("request_type") == "verify_existing" and request.get("requires_human_confirmation"):
            continue
        action = {
            "new_connection": "new",
            "dead_end_connection": "new",
            "road_widening": "widen",
            "road_hardening": "harden",
            "road_repair": "repair",
        }.get(str(request.get("request_type")), "verify")
        projects.append(
            {
                "project_id": request.get("request_id"),
                "name": request.get("reason"),
                "action": action,
                "start_place": request.get("start_node_id"),
                "end_place": request.get("end_node_id"),
                "start_demand_id": request.get("start_node_id"),
                "end_demand_id": request.get("end_node_id"),
                "start_geometry": None,
                "end_geometry": None,
                "served_node_ids": request.get("served_node_ids"),
                "source_bsm_list": request.get("source_bsm_list"),
                "related_intent_ids": request.get("related_intent_ids"),
                "target_id": request.get("target_id"),
                "target_ids": request.get("target_ids"),
                "requires_human_confirmation": request.get("requires_human_confirmation"),
                "recommended_road_class": request.get("recommended_road_class"),
                "recommended_width_m": request.get("recommended_width_m"),
            }
        )
    return {
        "type": "RoadProjectCollection",
        "schema_version": SCHEMA_VERSION,
        "generated_from": "stage2_6_road_planning_requests",
        "projects": projects,
    }


def _strip_runtime_features(features: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stripped: List[Dict[str, Any]] = []
    for feature in features:
        copied = {key: value for key, value in feature.items() if not key.startswith("_")}
        stripped.append(copied)
    return stripped


def build_planning_nodes(config: PlanningNodeBuildConfig) -> PlanningNodeBuildResult:
    """Run Stage 2.6 and write deterministic, GIS-readable artifacts."""

    config.validate()
    roads = _prepare_roads(config)
    boundary_metric = _prepare_boundary(config)
    local_point_index = _point_index(config.point_sources, config.display_crs)
    kg_point_index = _knowledge_graph_index(config.knowledge_graph_path, config.display_crs)
    point_index = _merge_indexes(local_point_index, kg_point_index)
    bundle_index = _geometry_index(config.bundle_geometry_sources, config.display_crs)
    manual_point_index, manual_spatial_index, manual_spatial_candidates, manual_confirmation_count = (
        _manual_confirmation_indexes(
            config.manual_confirmation_path,
            bundle_index,
            roads,
            config,
        )
    )
    kg_spatial_index, kg_spatial_candidates = _spatial_candidate_index(
        config.knowledge_graph_path,
        bundle_index,
        roads,
        config,
    )
    bound_spatial_index, bound_spatial_candidates = _spatial_candidate_index(
        config.bound_spatial_entities_path,
        bundle_index,
        roads,
        config,
    )
    intents = _road_intents(config.stage2_dir)
    demand_entities, _ = _entities_from_demands(config.stage2_dir)
    intent_entities = _entities_from_intents(intents)
    entities = _merge_entities([*demand_entities, *intent_entities])
    stage2_spatial_index, stage2_spatial_candidates = _stage2_entity_spatial_index(
        entities,
        bundle_index,
        roads,
        config,
    )
    # Binder candidates precede legacy candidates.  Ambiguous/bbox binder
    # records still carry requires_human_confirmation and cannot form nodes.
    spatial_index = _merge_indexes(bound_spatial_index, kg_spatial_index, stage2_spatial_index)
    spatial_candidates = [*bound_spatial_candidates, *kg_spatial_candidates, *stage2_spatial_candidates, *manual_spatial_candidates]
    located_runtime = _locate_entities(
        entities,
        manual_point_index,
        point_index,
        manual_spatial_index,
        spatial_index,
        roads,
        boundary_metric,
        config,
    )
    nodes = _planning_nodes(located_runtime, intents, roads, config)
    requests = _road_planning_requests(nodes, intents, config)
    located = _strip_runtime_features(located_runtime)
    review = _review_queue(located, nodes, requests)
    human_confirmation_template = _human_confirmation_template(review, located, nodes)
    kg_updates = _kg_updates(located, nodes, intents)
    iteration_records = _iteration_records(
        intents,
        entities,
        spatial_candidates,
        located,
        nodes,
        requests,
        review,
    )
    base_constraints_payload = _read_json(config.stage2_dir / "road_constraints.json")
    derived_constraints = _derived_constraints_from_restricted_entities(located, config.display_crs)
    constraints_payload = _merge_constraints_payload(base_constraints_payload, derived_constraints)

    entity_status_counts = Counter(
        str((feature.get("properties") or {}).get("location_status") or "unknown")
        for feature in located
    )
    node_action_counts = Counter(
        str((feature.get("properties") or {}).get("recommended_action") or "unknown")
        for feature in nodes
    )
    request_type_counts = Counter(str(request.get("request_type") or "unknown") for request in requests)
    source_counts = Counter(
        str((feature.get("properties") or {}).get("source") or "unknown")
        for feature in located
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "stage": "2.6",
        "input_stage2_dir": _relative(config.stage2_dir),
        "road_input": _relative(config.road_edges_path),
        "road_input_role": "standardized_current_network",
        "boundary_path": _relative(config.boundary_path) if config.boundary_path else None,
        "point_sources": [_relative(path) for path in config.point_sources],
        "bundle_geometry_sources": [_relative(path) for path in config.bundle_geometry_sources],
        "bound_spatial_entities_path": _relative(config.bound_spatial_entities_path)
        if config.bound_spatial_entities_path else None,
        "knowledge_graph_path": _relative(config.knowledge_graph_path)
        if config.knowledge_graph_path
        else None,
        "manual_confirmation_path": _relative(config.manual_confirmation_path)
        if config.manual_confirmation_path
        else None,
        "knowledge_graph_location_key_count": len(kg_point_index),
        "manual_confirmation_count": manual_confirmation_count,
        "manual_location_key_count": len(manual_point_index) + len(manual_spatial_index),
        "bundle_geometry_bsm_count": len(bundle_index),
        "knowledge_graph_spatial_key_count": len(kg_spatial_index),
        "bound_spatial_key_count": len(bound_spatial_index),
        "stage2_spatial_key_count": len(stage2_spatial_index),
        "spatial_candidate_count": len(spatial_candidates),
        "metric_crs": config.metric_crs,
        "display_crs": config.display_crs,
        "thresholds_m": {
            "cluster_distance": config.cluster_distance_m,
            "connected": config.connected_threshold_m,
            "near_network": config.near_network_threshold_m,
            "min_new_connection": config.min_new_connection_distance_m,
        },
        "road_intent_count": len(intents),
        "located_entity_count": len(located),
        "entity_location_status_counts": dict(sorted(entity_status_counts.items())),
        "entity_source_counts": dict(sorted(source_counts.items())),
        "planning_node_count": len(nodes),
        "planning_node_action_counts": dict(sorted(node_action_counts.items())),
        "road_planning_request_count": len(requests),
        "road_planning_request_type_counts": dict(sorted(request_type_counts.items())),
        "planning_kg_update_triple_count": int(kg_updates.get("triple_count") or 0),
        "human_review_count": review["review_count"],
        "human_confirmation_template_count": human_confirmation_template["confirmation_count"],
        "stage2_6_derived_constraint_count": len(derived_constraints),
        "retry_queue_count": len(iteration_records.get("retry_queue") or []),
        "leakage_guard": {
            "planned_road_read": False,
            "project_answer_layers_read": False,
            "rule": "Stage 2.6 uses current roads, boundary, annotation, local POI, KG, and manual confirmations only.",
        },
        "planning_gate": {
            "automatic_route_generation_allowed": review["review_count"] == 0,
            "reason": "All planning entities are confirmed."
            if review["review_count"] == 0
            else "Human review is required for low-confidence, candidate, proxy, unresolved, or abnormal spatial objects.",
        },
    }
    kg_retry_requests = _kg_retry_requests(iteration_records, report)
    report["kg_retry_request_count"] = int(kg_retry_requests.get("request_count") or 0)
    quality_gates = _spatial_quality_gates(
        located,
        nodes,
        requests,
        iteration_records,
        report,
    )
    report["quality_gate_status_counts"] = (
        (quality_gates.get("summary") or {}).get("status_counts") or {}
    )
    execute_trace = _execute_trace(report, iteration_records, kg_retry_requests, review)

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    road_intents_path = output_dir / "road_intents.json"
    kg_updates_path = output_dir / "planning_kg_updates.json"
    spatial_candidates_path = output_dir / "spatial_entity_candidates.geojson"
    located_path = output_dir / "located_planning_entities.geojson"
    nodes_path = output_dir / "planning_nodes.geojson"
    requests_path = output_dir / "road_planning_requests.json"
    quality_gates_path = output_dir / "spatial_quality_gates.json"
    iteration_records_path = output_dir / "iteration_records.json"
    kg_retry_requests_path = output_dir / "kg_retry_requests.json"
    execute_trace_path = output_dir / "spatial_preprocessing_trace.json"
    review_path = output_dir / "human_review_queue.json"
    human_confirmation_template_path = output_dir / "human_confirmation_template.json"
    report_path = output_dir / "stage2_6_report.json"

    _write_json(
        road_intents_path,
        {"type": "RoadIntentCollection", "schema_version": SCHEMA_VERSION, "intents": intents},
    )
    _write_json(kg_updates_path, kg_updates)
    _write_json(
        spatial_candidates_path,
        _feature_collection(
            "spatial_entity_candidates",
            config.display_crs,
            [
                {
                    "type": "Feature",
                    "id": candidate.get("candidate_id"),
                    "geometry": candidate.get("display_geometry") or candidate.get("geometry"),
                    "properties": {
                        key: value
                        for key, value in candidate.items()
                        if key not in {"geometry", "display_geometry"}
                    },
                }
                for candidate in spatial_candidates
            ],
        ),
    )
    _write_json(located_path, _feature_collection("located_planning_entities", config.display_crs, located))
    _write_json(nodes_path, _feature_collection("planning_nodes", config.display_crs, nodes))
    _write_json(
        requests_path,
        {
            "type": "RoadPlanningRequestCollection",
            "schema_version": SCHEMA_VERSION,
            "requests": requests,
        },
    )
    _write_json(iteration_records_path, iteration_records)
    _write_json(quality_gates_path, quality_gates)
    _write_json(kg_retry_requests_path, kg_retry_requests)
    _write_json(execute_trace_path, execute_trace)
    _write_json(review_path, review)
    _write_json(human_confirmation_template_path, human_confirmation_template)
    _write_json(report_path, report)

    _write_json(output_dir / "demand_points.geojson", _compatibility_demands(nodes, config.display_crs))
    _write_json(output_dir / "road_projects.json", _compatibility_projects(requests))
    _write_json(output_dir / "road_constraints.json", constraints_payload)

    return PlanningNodeBuildResult(
        output_dir=output_dir,
        road_intents_path=road_intents_path,
        kg_updates_path=kg_updates_path,
        spatial_candidates_path=spatial_candidates_path,
        located_entities_path=located_path,
        planning_nodes_path=nodes_path,
        road_planning_requests_path=requests_path,
        quality_gates_path=quality_gates_path,
        iteration_records_path=iteration_records_path,
        kg_retry_requests_path=kg_retry_requests_path,
        execute_trace_path=execute_trace_path,
        review_queue_path=review_path,
        human_confirmation_template_path=human_confirmation_template_path,
        report_path=report_path,
        report=report,
    )


__all__ = ["build_planning_nodes"]
