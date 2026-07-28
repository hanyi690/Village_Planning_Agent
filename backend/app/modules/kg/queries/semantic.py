"""Semantic query tools for LLM — combines RDF data + SemanticMemoryStore annotations.

Two categories of tools:
  1. Semantic tools: human-readable descriptions, entity/relation context
  2. Data tools: structured SPARQL results (delegated to tools.py)

All semantic tools populate SemanticMemoryStore on read (write-on-read pattern):
when an entity or relation has no existing annotation, a description is
auto-generated from RDF attributes and stored for future use.

Usage:
    from app.modules.kg.queries.semantic import get_entity_context, TOOL_META_SEMANTIC
"""
from typing import Any, Dict, List, Optional, Set

from rdflib import RDF as RDF_TERM, Literal, URIRef

from app.utils.logger import get_logger
from ..memory import EntityAnnotation, RelationAnnotation

logger = get_logger(__name__)

PLN_NS = "http://village-planning.org/ontology#"


def _to_uri(entity_uri: str) -> Optional[URIRef]:
    if not entity_uri:
        return None
    if isinstance(entity_uri, URIRef):
        return entity_uri
    if entity_uri.startswith("pln:"):
        return URIRef(PLN_NS + entity_uri[4:])
    if entity_uri.startswith("http://") or entity_uri.startswith("https://"):
        return URIRef(entity_uri)
    return URIRef(PLN_NS + entity_uri)


def _pred_name(p: Any) -> str:
    s = str(p)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def _obj_name(o: Any) -> str:
    s = str(o)
    if s.startswith("http://") or s.startswith("https://"):
        if "#" in s:
            return s.split("#")[-1]
        return s.split("/")[-1]
    return s


def _get_memory(kg) -> Any:
    return getattr(kg, 'memory', None)


def _lookup_entity_name(kg, uri_or_str) -> str:
    try:
        u = _to_uri(uri_or_str) if not isinstance(uri_or_str, URIRef) else uri_or_str
        if u is not None:
            for p, o in kg.g.predicate_objects(u):
                if _pred_name(p) == "name":
                    return str(o)
    except Exception:
        pass
    return ""


# ── Write-on-read annotation helpers ──

_ENTITY_TYPE_CN = {
    "Parcel": "地块",
    "Road": "道路",
    "ResidentialCluster": "居民点",
    "AdministrativeVillage": "行政村",
    "Village": "村庄",
    "Facility": "设施",
    "WaterBody": "水体",
    "Building": "建筑物",
    "ThreeZone": "三区",
    "ThreeLine": "三线管控区",
    "ControlLine": "控制线",
    "Zone": "分区",
    "Geofence": "地理围栏",
    "ConstructionBoundary": "建设边界",
    "ProtectionZone": "保护范围",
    "ZoneTarget": "分区目标",
    "FacilityTarget": "设施目标",
    "AxisTarget": "轴带目标",
    "RoadTarget": "道路目标",
    "PlannedParcel": "规划地块",
    "PlannedZone": "规划分区",
    "PlannedFacility": "规划设施",
    "PlannedRoad": "规划道路",
    "PlannedAxis": "规划轴带",
}


def _generate_entity_description(entity_type: str, attrs: Dict[str, str]) -> str:
    cn = _ENTITY_TYPE_CN.get(entity_type, entity_type)
    parts = [cn]

    if entity_type == "Parcel":
        bsm = attrs.get("bsm", "")
        dlbm = attrs.get("dlbm", "")
        area = attrs.get("area_ha", "")
        zt = attrs.get("current_zone_type", "")
        pz = attrs.get("planning_zone", "")
        if bsm:
            parts.append(bsm)
        if dlbm:
            parts.append(f"地类编码{dlbm}")
        if area:
            parts.append(f"面积{area}公顷")
        if zt:
            parts.append(f"({zt})")
        if pz:
            parts.append(f"规划分区:{pz}")

    elif entity_type == "Road":
        name = attrs.get("name", "")
        level = attrs.get("road_level", "")
        length = attrs.get("length", "")
        if name:
            parts.append(name.replace("道路_", ""))
        if level:
            parts.append(level)
        if length:
            parts.append(f"长度{length}m")

    elif entity_type == "ResidentialCluster":
        name = attrs.get("name", "")
        if name:
            parts.append(name)

    elif entity_type == "Facility":
        name = attrs.get("name", "")
        ftype = attrs.get("facility_type", "")
        if name:
            parts.append(name)
        if ftype:
            parts.append(f"({ftype})")

    elif entity_type == "AdministrativeVillage":
        name = attrs.get("name", "")
        if name:
            parts.append(name)

    elif entity_type in ("ThreeLine", "ThreeZone", "Zone", "ControlLine"):
        name = attrs.get("name", "")
        code = attrs.get("code", "")
        if name:
            parts.append(name)
        if code:
            parts.append(f"编码{code}")

    elif entity_type in ("ZoneTarget", "FacilityTarget", "AxisTarget", "RoadTarget"):
        name = attrs.get("name", "")
        desc = attrs.get("description", "")
        if name:
            parts.append(name)
        if desc:
            parts.append(desc)

    elif entity_type == "WaterBody":
        name = attrs.get("name", "")
        if name:
            parts.append(name.replace("水域_", ""))

    return " ".join(parts)


def _ensure_entity_annotation(kg, uri_str: str, entity_type: str,
                               attributes: Dict[str, str]) -> None:
    memory = _get_memory(kg)
    if memory is None:
        return
    if memory.get_entity_semantics(uri_str) is not None:
        return
    desc = _generate_entity_description(entity_type, attributes)
    if not desc:
        desc = f"{_ENTITY_TYPE_CN.get(entity_type, entity_type)} {uri_str.split('/')[-1]}"
    memory.add_entity_annotation(EntityAnnotation(
        entity_uri=uri_str,
        entity_type=entity_type,
        description=desc,
    ))


_RELATION_PRED_CN = {
    "sfTouches": "相邻",
    "touches": "相邻",
    "nearby": "邻近",
    "connected_via_road": "道路连接",
    "sfWithin": "位于",
    "within_zone": "位于",
    "located_in": "位于",
    "sfIntersects": "相交",
    "intersects": "相交",
    "sfContains": "包含",
    "contains": "包含",
    "designated_as": "被划定为",
    "derived_from": "源自",
    "serves": "服务于",
    "connects": "连接",
    "delineates": "界定了",
    "has_road": "有道路",
    "relates_to_anchor": "关联锚点",
    "has_zone": "有分区",
    "has_facility": "有设施",
    "has_axis": "有发展轴带",
    "has_planning_scope": "有规划范围",
}


def _generate_relation_description(pred_name: str, obj_uri_str: str, kg=None) -> str:
    pred_cn = _RELATION_PRED_CN.get(pred_name, pred_name)
    obj_short = _obj_name(obj_uri_str)
    if kg is not None:
        obj_name = _lookup_entity_name(kg, obj_uri_str)
        if obj_name:
            obj_short = obj_name
    if pred_name in ("sfTouches", "touches", "nearby", "connected_via_road"):
        return f"与{obj_short}{pred_cn}"
    if pred_name in ("sfWithin", "sfIntersects", "sfContains",
                     "within_zone", "located_in", "intersects", "contains",
                     "designated_as", "derived_from", "serves", "connects",
                     "delineates", "relates_to_anchor"):
        return f"{pred_cn}{obj_short}"
    # Other predicates (has_road, has_zone, etc.)
    return f"{pred_cn}: {obj_short}"


def _ensure_relation_annotation(kg, subj_str: str, pred_full: str,
                                 obj_str: str, pred_name: str) -> None:
    memory = _get_memory(kg)
    if memory is None:
        return
    if memory.get_relation_semantics(subj_str, pred_full, obj_str) is not None:
        return
    desc = _generate_relation_description(pred_name, obj_str, kg)
    memory.add_relation_annotation(RelationAnnotation(
        subject_uri=subj_str,
        predicate=pred_full,
        object_uri=obj_str,
        description=desc,
        derived_from="rule_generated",
    ))


# ── Entity context ──


def get_entity_context(kg, entity_uri: str) -> Dict[str, Any]:
    try:
        uri = _to_uri(entity_uri)
        if uri is None:
            return {"error": "entity_uri is required"}

        result = {"uri": entity_uri, "type": None, "attributes": {}, "annotations": None}

        for p, o in kg.g.predicate_objects(uri):
            pred = _pred_name(p)
            if pred == "type":
                result["type"] = _obj_name(o)
            else:
                result["attributes"][pred] = str(o)

        if not result["type"]:
            return {"error": f"entity not found: {entity_uri}", "uri": entity_uri}

        _ensure_entity_annotation(kg, str(uri), result["type"], result["attributes"])

        memory = _get_memory(kg)
        if memory is not None:
            result["annotations"] = memory.get_entity_semantics(str(uri))

        return result
    except Exception as e:
        logger.error("get_entity_context failed: %s", e)
        return {"error": str(e), "uri": entity_uri}


# ── Entity relations ──


def get_entity_relations(kg, entity_uri: str) -> List[Dict[str, Any]]:
    try:
        uri = _to_uri(entity_uri)
        if uri is None:
            return [{"error": "entity_uri is required"}]

        relations = []
        memory = _get_memory(kg)

        types = list(kg.g.objects(uri, RDF_TERM.type))
        if not types:
            return [{"error": f"entity not found: {entity_uri}"}]

        # Outgoing
        for p, o in kg.g.predicate_objects(uri):
            pred = _pred_name(p)
            if pred == "type":
                continue
            obj = _obj_name(o)
            _ensure_relation_annotation(kg, str(uri), str(p), str(o), pred)
            ann = None
            if memory is not None:
                ann = memory.get_relation_semantics(str(uri), str(p), str(o))
            relations.append({
                "predicate": pred,
                "direction": "outgoing",
                "object": obj,
                "description": ann.get("description") if ann else None,
                "quantitative_detail": ann.get("quantitative_detail") if ann else None,
            })

        # Incoming
        for s, p in kg.g.subject_predicates(object=uri):
            pred = _pred_name(p)
            if pred == "type":
                continue
            subj = _obj_name(s)
            _ensure_relation_annotation(kg, str(s), str(p), str(uri), pred)
            ann = None
            if memory is not None:
                ann = memory.get_relation_semantics(str(s), str(p), str(uri))
            relations.append({
                "predicate": pred,
                "direction": "incoming",
                "object": subj,
                "description": ann.get("description") if ann else None,
                "quantitative_detail": ann.get("quantitative_detail") if ann else None,
            })

        return relations
    except Exception as e:
        logger.error("get_entity_relations failed: %s", e)
        return [{"error": str(e), "uri": entity_uri}]


# ── Parcel semantic context ──


def _find_parcel_uri(kg, bsm: str) -> Optional[URIRef]:
    """Find parcel URI by BSM using SPARQL with BSM filter."""
    try:
        escaped_bsm = bsm.replace('"', '\\"')
        rows = kg.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:Parcel ; pln:bsm ?bsm_val . "
            f'FILTER(?bsm_val = "{escaped_bsm}") }}',
        )
        for r in rows:
            uri = r.get("p")
            if uri:
                return _to_uri(uri)
    except Exception:
        pass

    # Fallback: direct triple pattern match
    try:
        from rdflib import Literal as RdfLiteral, URIRef as RdfURIRef
        bsm_pred = RdfURIRef(PLN_NS + "bsm")
        for s, _, _ in kg.g.triples((None, bsm_pred, RdfLiteral(bsm))):
            for t in kg.g.objects(s, RDF_TERM.type):
                if _obj_name(t) == "Parcel":
                    return s
    except Exception:
        pass

    return None


def get_parcel_semantic_context(kg, bsm: str) -> Dict[str, Any]:
    try:
        if not bsm:
            return {"error": "bsm is required"}

        parcel_uri = _find_parcel_uri(kg, bsm)
        if parcel_uri is None:
            return {"bsm": bsm, "error": "parcel not found"}

        uri_str = str(parcel_uri)

        # Attributes
        attrs = {}
        for p, o in kg.g.predicate_objects(parcel_uri):
            pred = _pred_name(p)
            if pred in ("type", "bsm"):
                continue
            attrs[pred] = str(o)

        _ensure_entity_annotation(kg, uri_str, "Parcel", {**attrs, "bsm": bsm})

        # Relations
        relations = []
        memory = _get_memory(kg)
        for p, o in kg.g.predicate_objects(parcel_uri):
            pred = _pred_name(p)
            if pred in ("type", "bsm"):
                continue
            obj = _obj_name(o)
            _ensure_relation_annotation(kg, uri_str, str(p), str(o), pred)
            ann = None
            if memory is not None:
                ann = memory.get_relation_semantics(uri_str, str(p), str(o))
            entry = {"predicate": pred, "object": obj}
            if ann:
                entry["description"] = ann.get("description")
                if ann.get("quantitative_detail"):
                    entry.update(ann["quantitative_detail"])
            relations.append(entry)

        result = {
            "bsm": bsm,
            "uri": uri_str,
            "attributes": attrs,
            "relations": relations,
        }

        if memory is not None:
            result["annotations"] = memory.get_entity_semantics(uri_str)

        return result
    except Exception as e:
        logger.error("get_parcel_semantic_context failed: bsm=%s, %s", bsm, e)
        return {"bsm": bsm, "error": str(e)}


# ── Village semantic summary ──


def get_village_semantic_summary(kg) -> Dict[str, Any]:
    try:
        entity_counts = {}
        for s, _, o in kg.g.triples((None, RDF_TERM.type, None)):
            t = _obj_name(o)
            entity_counts[t] = entity_counts.get(t, 0) + 1

        relation_counts = {}
        for s, p, o in kg.g.triples((None, None, None)):
            pred = _pred_name(p)
            if pred == "type":
                continue
            relation_counts[pred] = relation_counts.get(pred, 0) + 1

        name = ""
        for _, _, o in kg.g.triples((None, None, None)):
            s = str(_obj_name(o))
            if "村委会" in s or "村" in s:
                name = s
                break

        # Planning zone distribution (from L1 parcel attributes)
        planning_zone_dist: Dict[str, int] = {}
        for s, p, o in kg.g.triples((None, None, None)):
            pred = _pred_name(p)
            if pred == "planning_zone":
                zone_str = str(o)
                if zone_str in ("生态保护区", "生态控制区", "农田保护区",
                                "一般农业区", "村庄建设区", "林业发展区"):
                    planning_zone_dist[zone_str] = planning_zone_dist.get(zone_str, 0) + 1

        result = {
            "village_name": name,
            "parcel_count": entity_counts.get("Parcel", 0),
            "entity_counts": entity_counts,
            "relation_counts": relation_counts,
            "planning_zone_distribution": planning_zone_dist,
            "total_triples": len(kg.g),
        }

        memory = _get_memory(kg)
        if memory is not None:
            village_uri = str(PLN_NS + "village")
            if memory.get_entity_semantics(village_uri) is None:
                desc_parts = [f"村庄{name}" if name else "村庄"]
                pcount = entity_counts.get("Parcel", 0)
                rcount = entity_counts.get("Road", 0)
                scount = entity_counts.get("ResidentialCluster", 0)
                fcount = entity_counts.get("Facility", 0)
                if pcount:
                    desc_parts.append(f"共{pcount}个地块")
                if rcount:
                    desc_parts.append(f"{rcount}条道路")
                if scount:
                    desc_parts.append(f"{scount}个居民点")
                if fcount:
                    desc_parts.append(f"{fcount}个设施点")
                if planning_zone_dist:
                    zones_desc = ", ".join(
                        f"{k}{v}块" for k, v in sorted(planning_zone_dist.items())
                    )
                    desc_parts.append(f"规划分区: {zones_desc}")
                desc_parts.append(f"三元组总数{len(kg.g)}")
                memory.add_entity_annotation(EntityAnnotation(
                    entity_uri=village_uri,
                    entity_type="AdministrativeVillage",
                    description=", ".join(desc_parts),
                ))
            result["annotation_count"] = len(memory.entity_annotations)

        return result
    except Exception as e:
        logger.error("get_village_semantic_summary failed: %s", e)
        return {"error": str(e)}


# ── Cross-layer entity queries ──


def get_entity_by_bsm(kg, bsm: str, entity_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Find any entity (L1 or L4) by BSM, across all layers.

    Args:
        kg: PlanningKG instance.
        bsm: BSM identifier string.
        entity_type: Optional filter (e.g. "Parcel", "Road", "Facility").
            When specified, only returns entities of that type.

    Returns entity context with layer info, or None if not found.
    """
    try:
        if not bsm:
            return None

        from rdflib import Literal as RdfLiteral, URIRef as RdfURIRef
        bsm_pred = RdfURIRef(PLN_NS + "bsm")

        for s, _, _ in kg.g.triples((None, bsm_pred, RdfLiteral(bsm))):
            entity_types = list(kg.g.objects(s, RDF_TERM.type))
            if not entity_types:
                continue
            type_name = _obj_name(entity_types[0])
            if entity_type and type_name != entity_type:
                continue

            uri_str = str(s)
            attrs = {"bsm": bsm}
            for p, v in kg.g.predicate_objects(s):
                pred = _pred_name(p)
                if pred != "type":
                    attrs[pred] = str(v)

            layer = "L1"
            if type_name.startswith("Planned"):
                layer = "L4"
            elif type_name.endswith("Target"):
                layer = "L3"

            _ensure_entity_annotation(kg, uri_str, type_name, attrs)

            result = {
                "uri": uri_str,
                "type": type_name,
                "layer": layer,
                "attributes": attrs,
            }

            memory = _get_memory(kg)
            if memory is not None:
                result["annotations"] = memory.get_entity_semantics(uri_str)

            return result

        return None
    except Exception as e:
        logger.error("get_entity_by_bsm failed: bsm=%s, %s", bsm, e)
        return None


def get_parcels_by_planning_zone(kg, planning_zone: str) -> List[Dict[str, Any]]:
    """Find all L1 parcels belonging to a given planning zone.

    Args:
        planning_zone: Planning zone name (e.g. "村庄建设区", "农田保护区")

    Returns:
        List of parcel summaries with BSM, DLBM, area, and relations.
    """
    try:
        from app.modules.schema.encodings.code_sets import PLANNING_ZONE_NAMES, normalize_landuse

        # Validate planning zone
        valid_zones = set(PLANNING_ZONE_NAMES)
        if planning_zone not in valid_zones:
            return [{"error": f"Invalid planning zone: {planning_zone}. Valid: {valid_zones}"}]

        parcels = []
        seen: Set[str] = set()

        for s, p, o in kg.g.triples((None, None, None)):
            pred = _pred_name(p)
            if pred == "planning_zone":
                zone_val = str(o)
                if zone_val == planning_zone:
                    # This is a parcel in the target zone
                    bsm = None
                    dlbm = None
                    area = None
                    for p_subj, v in kg.g.predicate_objects(s):
                        pn = _pred_name(p_subj)
                        if pn == "bsm":
                            bsm = str(v)
                        elif pn == "dlbm":
                            dlbm = str(v)
                        elif pn == "area_ha":
                            area = str(v)

                    if bsm and bsm not in seen:
                        seen.add(bsm)
                        parcels.append({
                            "bsm": bsm,
                            "dlbm": dlbm or "",
                            "area_ha": area or "",
                            "planning_zone": planning_zone,
                            "uri": str(s),
                        })

        # Attach relations for each parcel
        memory = _get_memory(kg)
        for p in parcels:
            uri = _to_uri(p["uri"])
            if uri is None:
                continue
            relations = []
            for pred, obj in kg.g.predicate_objects(uri):
                pn = _pred_name(pred)
                if pn in ("type", "bsm", "dlbm", "area_ha", "planning_zone", "vne_code"):
                    continue
                obj_name = _obj_name(obj)
                ann = None
                if memory is not None:
                    ann = memory.get_relation_semantics(p["uri"], str(pred), str(obj))
                entry = {"predicate": pn, "object": obj_name}
                if ann:
                    entry["description"] = ann.get("description")
                relations.append(entry)
            p["relations"] = relations

        return parcels
    except Exception as e:
        logger.error("get_parcels_by_planning_zone failed: %s", e)
        return [{"error": str(e)}]


def get_l4_derived_from_l1(kg, l1_bsm: str) -> List[Dict[str, Any]]:
    """Find all L4 planned entities derived from a given L1 parcel.

    Traces the derived_from relationship: L4 PlannedParcel → L1 Parcel.
    """
    try:
        results = []
        for s, _, o in kg.g.triples((None, None, None)):
            pn = _pred_name(o)
            if pn == "derived_from":
                # o points to the L1 entity
                # s is the L4 entity
                for subj, _, derived_val in kg.g.triples((s, None, None)):
                    if str(derived_val) == l1_bsm or l1_bsm in str(derived_val):
                        entity_types = list(kg.g.objects(subj, RDF_TERM.type))
                        etype = _obj_name(entity_types[0]) if entity_types else "Unknown"

                        attrs = {}
                        for p, v in kg.g.predicate_objects(subj):
                            pn2 = _pred_name(p)
                            if pn2 != "type":
                                attrs[pn2] = str(v)

                        results.append({
                            "uri": str(subj),
                            "type": etype,
                            "attributes": attrs,
                        })

        return results
    except Exception as e:
        logger.error("get_l4_derived_from_l1 failed: %s", e)
        return [{"error": str(e)}]


# ── Tool metadata for LLM ──

def get_village_constraint_coverage(kg) -> List[Dict[str, Any]]:
    """Get all parcels with constraint polygon coverage, with human-readable descriptions.

    Internally delegates to kg.get_constraint_coverage() (which uses ConstraintIndex),
    then augments with semantic annotations for LLM consumption.

    Returns:
        List of dicts with bsm, dlbm, area_ha, zone_type, planning_zone, constraints,
        and a human-readable summary.
    """
    try:
        raw = kg.get_constraint_coverage()
        if not raw:
            return [{"summary": "未检测到与约束面的重叠", "parcel_count": 0}]

        results = []
        for item in raw:
            constraint_names = {
                "farmland_protection": "永久基本农田",
                "ecological_redline": "生态保护红线",
                "historical_protection": "历史保护范围",
                "urban_dev_boundary": "城镇开发边界",
                "village_dev_boundary": "村庄建设边界",
                "hazard_control": "灾害防控线",
                "flood_control": "洪涝控制线",
                "construction_zone": "有条件建设区",
            }
            descs = []
            for c in item["constraints"]:
                cn = constraint_names.get(c["constraint_type"], c["constraint_type"])
                pct = c.get("overlap_pct", 0) * 100
                descs.append(f"{cn}(重叠{pct:.1f}%)")
            summary = f"地块 {item['bsm']} 与 {', '.join(descs)} 重叠" if descs else "无约束重叠"

            memory = _get_memory(kg)
            if memory is not None:
                memory.add_entity_annotation(EntityAnnotation(
                    entity_uri=f"pln:parcel_{item['bsm']}",
                    entity_type="Parcel",
                    description=summary,
                ))

            results.append({
                "bsm": item["bsm"],
                "dlbm": item["dlbm"],
                "area_ha": item["area_ha"],
                "zone_type": item["zone_type"],
                "planning_zone": item["planning_zone"],
                "constraints": item["constraints"],
                "summary": summary,
            })

        total = len(results)
        constrained_bsms = [r["bsm"] for r in results]
        results.insert(0, {
            "summary": f"共 {total} 个地块与约束面重叠",
            "parcel_count": total,
            "constrained_bsms": constrained_bsms,
        })
        return results
    except Exception as e:
        logger.error("get_village_constraint_coverage failed: %s", e)
        return [{"error": str(e)}]


# ── LLM-friendly semantic list queries (return human-readable text arrays) ──

_LLM_DIRECTION_CN = {
    "north": "北侧", "south": "南侧", "east": "东侧", "west": "西侧",
    "northeast": "东北侧", "southeast": "东南侧", "northwest": "西北侧", "southwest": "西南侧",
}

_DLBM_TO_LANDUSE = {
    "0101": "水田", "0102": "水浇地", "0103": "旱地",
    "0201": "果园", "0204": "其他园地",
    "0301": "乔木林地", "0302": "竹林地", "0307": "其他林地",
    "0401": "天然牧草地", "0403": "人工牧草地",
    "0701": "城镇住宅用地", "0702": "农村宅基地",
    "0809": "公用设施用地", "0810": "公园与绿地",
    "1001": "工业用地", "1003": "采矿用地",
    "1101": "物流仓储用地",
    "1202": "公路用地", "1206": "管道运输用地",
    "2001": "空闲地",
    "2101": "商业服务业用地", "2102": "商务金融用地",
    "2121": "商业用地", "2124": "餐饮用地",
}


def _dlbm_to_name(dlbm: str) -> str:
    return _DLBM_TO_LANDUSE.get(dlbm, f"地类{dlbm}")


def _sparql_rows(kg, template_name: str, **bindings) -> List[Dict[str, str]]:
    """Execute a SPARQL template directly, bypassing semantic dispatch.

    Semantic functions MUST use this instead of query_kg() to avoid recursion.
    """
    from app.modules.kg.queries.sparql import QUERY_TEMPLATES
    from rdflib import Literal

    sparql = QUERY_TEMPLATES.get(template_name)
    if not sparql:
        return []
    init_b = {}
    for k, v in bindings.items():
        if v is not None:
            init_b[k] = Literal(str(v))
    try:
        results = kg.g.query(sparql, initBindings=init_b if init_b else None)
        rows = []
        for row in results:
            if hasattr(row, 'asdict'):
                rows.append({str(k): str(v) if v is not None else None for k, v in row.asdict().items()})
            elif isinstance(row, (tuple, list)):
                rd = {}
                if hasattr(results, 'vars'):
                    for i, var in enumerate(results.vars):
                        if i < len(row):
                            rd[str(var)] = str(row[i]) if row[i] is not None else None
                rows.append(rd)
        return rows
    except Exception as e:
        logger.error("_sparql_rows failed: template=%s, %s", template_name, e)
        return []


def get_parcels_semantic_list(kg) -> List[Dict[str, Any]]:
    """All L1 parcels as human-readable descriptions.

    Returns list of {bsm, dlbm, description} where description is
    LLM-friendly text like 'P001: 宅基地(0701) 0.15ha'.
    """
    try:
        raw = _sparql_rows(kg, "get_village_parcels")
        results = []
        for r in raw:
            bsm = r.get("bsm", "")
            dlbm = r.get("dlbm", "")
            area = r.get("area_ha", "")
            zone = r.get("planning_zone", "")
            landuse_name = _dlbm_to_name(dlbm)
            parts = [f"{bsm}: {landuse_name}({dlbm})"]
            if area:
                parts.append(f"{area}ha")
            if zone:
                parts.append(zone)
            results.append({
                "bsm": bsm,
                "dlbm": dlbm,
                "area_ha": area,
                "planning_zone": zone,
                "description": " ".join(parts),
            })
        return results
    except Exception as e:
        logger.error("get_parcels_semantic_list failed: %s", e)
        return [{"error": str(e)}]


def get_parcel_detail_semantic(kg, bsm: str) -> List[Dict[str, Any]]:
    """Single parcel detail with relations, as human-readable description.

    Returns list with one item containing description + structured data.
    Description is like:
    'P001: 宅基地(0701) 0.15ha, 位于刘村北侧, 相邻P002(耕地), 靠近乡道Y123'
    """
    try:
        ctx = get_parcel_semantic_context(kg, bsm)
        if "error" in ctx:
            return [ctx]

        attrs = ctx.get("attributes", {})
        relations = ctx.get("relations", [])
        annotations = ctx.get("annotations", {})

        dlbm = attrs.get("dlbm", "")
        area = attrs.get("area_ha", "")
        zone = attrs.get("planning_zone", "")
        landuse_name = _dlbm_to_name(dlbm)

        parts = [f"{bsm}: {landuse_name}({dlbm})"]
        if area:
            parts.append(f"{area}ha")
        if zone:
            parts.append(zone)

        # Relations -> text
        rel_parts = []
        for rel in relations:
            pred = rel.get("predicate", "")
            obj = rel.get("object", "")
            desc = rel.get("description", "")
            if desc:
                rel_parts.append(desc)
            elif pred in ("sfTouches", "touches"):
                rel_parts.append(f"相邻{obj}")
            elif pred in ("nearby",):
                rel_parts.append(f"邻近{obj}")
            elif pred in ("connected_via_road",):
                rel_parts.append(f"道路连接{obj}")
            elif pred in ("sfWithin", "within_zone", "located_in"):
                rel_parts.append(f"位于{obj}")
        if rel_parts:
            parts.append("，".join(rel_parts[:4]))

        description = "，".join(parts)

        return [{
            "bsm": bsm,
            "dlbm": dlbm,
            "area_ha": area,
            "planning_zone": zone,
            "landuse_name": landuse_name,
            "description": description,
            "relations": relations,
        }]
    except Exception as e:
        logger.error("get_parcel_detail_semantic failed: bsm=%s, %s", bsm, e)
        return [{"bsm": bsm, "error": str(e)}]


def get_parcel_neighbors_semantic(kg, bsm: str) -> List[Dict[str, Any]]:
    """Neighbors of a parcel, with semantic descriptions.

    Returns list of {bsm, dlbm, description} for each neighbor.
    """
    try:
        raw = _sparql_rows(kg, "get_parcel_neighbors", bsm=bsm)
        results = []
        seen = set()
        for r in raw:
            nbr = r.get("neighbor", "")
            if nbr in seen:
                continue
            seen.add(nbr)
            nbr_dlbm = r.get("neighbor_dlbm", "")
            nbr_area = r.get("neighbor_area", "")
            relation = r.get("relation", "touches")
            landuse_name = _dlbm_to_name(nbr_dlbm)
            rel_cn = {"touches": "相邻", "nearby": "邻近", "connected_via_road": "道路连接"}.get(relation, relation)
            parts = [f"{nbr}: {landuse_name}({nbr_dlbm})"]
            if nbr_area:
                parts.append(f"{nbr_area}ha")
            parts.append(rel_cn)
            results.append({
                "bsm": nbr,
                "dlbm": nbr_dlbm,
                "area_ha": nbr_area,
                "relation": relation,
                "description": "，".join(parts),
            })
        if not results:
            results.append({"bsm": bsm, "description": f"地块{bsm}无相邻地块数据"})
        return results
    except Exception as e:
        logger.error("get_parcel_neighbors_semantic failed: bsm=%s, %s", bsm, e)
        return [{"bsm": bsm, "error": str(e)}]


def get_facilities_semantic_list(kg) -> List[Dict[str, Any]]:
    """All facilities as human-readable descriptions."""
    try:
        raw = _sparql_rows(kg, "get_facility_locations")
        results = []
        for r in raw:
            name = r.get("name", "")
            ftype = r.get("facility_type", "")
            lon = r.get("lon", "")
            lat = r.get("lat", "")
            parts = [name or ftype or "设施"]
            if lon and lat:
                parts.append(f"({lon},{lat})")
            results.append({
                "name": name,
                "facility_type": ftype,
                "location": f"{lon},{lat}" if lon and lat else "",
                "description": " ".join(parts),
            })
        if not results:
            results.append({"description": "无设施数据"})
        return results
    except Exception as e:
        logger.error("get_facilities_semantic_list failed: %s", e)
        return [{"error": str(e)}]


def get_road_network_semantic(kg) -> List[Dict[str, Any]]:
    """All roads as human-readable descriptions."""
    try:
        raw = _sparql_rows(kg, "get_road_network")
        results = []
        for r in raw:
            name = r.get("name", "")
            level = r.get("road_level", "")
            length_m = r.get("length_m", "")
            parts = [name or level or "道路"]
            if level:
                parts.append(level)
            if length_m:
                parts.append(f"{length_m}m")
            results.append({
                "name": name,
                "road_level": level,
                "length_m": length_m,
                "description": " ".join(parts),
            })
        if not results:
            results.append({"description": "无道路数据"})
        return results
    except Exception as e:
        logger.error("get_road_network_semantic failed: %s", e)
        return [{"error": str(e)}]


def get_designated_zones_semantic(kg) -> List[Dict[str, Any]]:
    """All designated zones / constraint parcels as human-readable descriptions."""
    try:
        raw = get_village_constraint_coverage(kg)
        results = []
        for r in raw:
            if "summary" in r and "bsm" not in r:
                results.append(r)
                continue
            bsm = r.get("bsm", "")
            zone_type = r.get("planning_zone", "")
            dlbm = r.get("dlbm", "")
            area = r.get("area_ha", "")
            summary = r.get("summary", "")
            landuse_name = _dlbm_to_name(dlbm)
            parts = [f"{bsm}: {landuse_name}({dlbm})"]
            if area:
                parts.append(f"{area}ha")
            if zone_type:
                parts.append(zone_type)
            results.append({
                "bsm": bsm,
                "dlbm": dlbm,
                "area_ha": area,
                "planning_zone": zone_type,
                "description": "，".join(parts),
                "summary": summary,
            })
        return results
    except Exception as e:
        logger.error("get_designated_zones_semantic failed: %s", e)
        return [{"error": str(e)}]


TOOL_META_SEMANTIC = {
    "name": "query_kg_semantics",
    "description": (
        "Query the village planning knowledge graph for SEMANTIC context. "
        "Returns human-readable descriptions, entity annotations, and relation explanations. "
        "Use this when the LLM needs to understand the meaning/spatial context of entities."
    ),
    "functions": {
        "get_entity_context": {
            "description": "Get entity context with attributes and semantic annotations",
            "parameters": {
                "entity_uri": {
                    "type": "string",
                    "description": "Entity URI (e.g. pln:ResidentialCluster/刘村, or a full URI)",
                },
            },
        },
        "get_entity_relations": {
            "description": "Get all relations for an entity with semantic descriptions (outgoing + incoming)",
            "parameters": {
                "entity_uri": {
                    "type": "string",
                    "description": "Entity URI",
                },
            },
        },
        "get_parcel_semantic_context": {
            "description": "Get parcel context with attributes, spatial relations, and semantic annotations",
            "parameters": {
                "bsm": {
                    "type": "string",
                    "description": "Parcel BSM identifier (e.g. 441426211000055682)",
                },
            },
        },
        "get_village_semantic_summary": {
            "description": "Get a human-readable summary of the entire village KG (entity counts, relation counts, planning zone distribution)",
            "parameters": {},
        },
        "get_entity_by_bsm": {
            "description": "Find any entity (L1 current or L4 planned) by BSM, across all layers. Returns type, layer, attributes, and annotations.",
            "parameters": {
                "bsm": {
                    "type": "string",
                    "description": "Entity BSM identifier",
                },
            },
        },
        "get_parcels_by_planning_zone": {
            "description": "Find all L1 parcels belonging to a given planning zone. Returns parcel BSM, DLBM, area, and spatial relations.",
            "parameters": {
                "planning_zone": {
                    "type": "string",
                    "description": "Planning zone name: 生态保护区/生态控制区/农田保护区/一般农业区/村庄建设区/林业发展区",
                },
            },
        },
        "get_l4_derived_from_l1": {
            "description": "Find all L4 planned entities derived from a given L1 parcel (traces derived_from relationship).",
            "parameters": {
                "l1_bsm": {
                    "type": "string",
                    "description": "L1 parcel BSM identifier",
                },
            },
        },
        "get_village_constraint_coverage": {
            "description": "Get all parcels that overlap constraint polygons (three lines, protected zones). Returns human-readable descriptions of which parcels are constrained by which protection zones, with overlap percentage.",
            "parameters": {},
        },
    },
}


# ============================================================
# v4.8 - get_entity_semantics: entity-type-level semantic layer query
# ============================================================

def get_entity_semantics(kg, entity_label: str = "", entity_type: str = "", bsm: str = "") -> Dict[str, Any]:
    """Get semantic-layer info for an entity or entity type.

    Returns taxonomic_parent, legal_constraint, allowed_operations, and encoding
    bridges for the given entity. This is the semantic layer that PARSE needs to
    understand what "水田", "农田保护区", "生态红线" mean spatially and legally.

    Args:
        kg: PlanningKG instance.
        entity_label: Chinese semantic label (e.g. "水田", "宅基地", "农田保护区").
        entity_type: RDF type name (e.g. "Parcel", "Zone"). Optional.
        bsm: BSM of a specific entity to look up. Optional.

    Returns:
        Dict with:
          - taxonomic_parent: classification hierarchy (e.g. "水田" -> "耕地" -> "农业用地")
          - legal_constraint: legal restriction (e.g. "forbid_construction")
          - allowed_operations: list of permitted SpatialOperation actions
          - encoding_bridges: dlbm -> ghytbm -> vne mappings
          - matching_entities: count and sample BSMs
    """
    try:
        from ..ontology import SemanticPredicates
        taxonomic_parent = SemanticPredicates.taxonomic_parent
        legal_constraint = SemanticPredicates.legal_constraint
        allowed_operations = SemanticPredicates.allowed_operations
        has_semantic_label = SemanticPredicates.has_semantic_label
        semantic_group = SemanticPredicates.semantic_group

        result: Dict[str, Any] = {
            "query_label": entity_label,
            "query_type": entity_type,
            "taxonomic_parent": "",
            "legal_constraint": "",
            "allowed_operations": [],
            "encoding_bridges": {},
            "matching_entities": {"count": 0, "sample_bsms": []},
        }

        # If BSM provided, look up specific entity
        if bsm:
            from rdflib import Literal as RdfLiteral
            bsm_pred = URIRef(PLN_NS + "bsm")
            for s, _, _ in kg.g.triples((None, bsm_pred, RdfLiteral(bsm))):
                # Get type
                for _, _, t in kg.g.triples((s, RDF_TERM.type, None)):
                    result["query_type"] = _obj_name(t)
                    break
                # Get all attributes
                attrs = {}
                for p, o in kg.g.predicate_objects(s):
                    pn = _pred_name(p)
                    if pn == "type":
                        continue
                    attrs[pn] = str(o)
                # Extract semantic info
                if "taxonomic_parent" in attrs:
                    result["taxonomic_parent"] = attrs["taxonomic_parent"]
                if "legal_constraint" in attrs:
                    result["legal_constraint"] = attrs["legal_constraint"]
                if "has_semantic_label" in attrs:
                    result["query_label"] = attrs["has_semantic_label"]
                    entity_label = attrs["has_semantic_label"]
                # Collect allowed_operations
                ops = []
                for _, _, o in kg.g.triples((s, allowed_operations, None)):
                    ops.append(str(o))
                result["allowed_operations"] = ops
                # Encoding bridges
                result["encoding_bridges"] = {
                    "dlbm": attrs.get("dlbm", ""),
                    "dlmc": attrs.get("dlmc", ""),
                    "current_zone_type": attrs.get("current_zone_type", ""),
                    "planning_zone": attrs.get("planning_zone", ""),
                    "primary_zone": attrs.get("primary_zone", ""),
                }
                break

        # If entity_label provided (no BSM), find entities with that label
        elif entity_label:
            matching_uris = []
            taxonomic_parent_val = ""
            legal_constraint_val = ""
            ops_set = set()

            for s, _, _ in kg.g.triples((None, has_semantic_label, Literal(entity_label))):
                matching_uris.append(s)
                # Collect semantic info from matching entities
                if not taxonomic_parent_val:
                    for _, _, o in kg.g.triples((s, taxonomic_parent, None)):
                        taxonomic_parent_val = str(o)
                        break
                if not legal_constraint_val:
                    for _, _, o in kg.g.triples((s, legal_constraint, None)):
                        legal_constraint_val = str(o)
                        break
                for _, _, o in kg.g.triples((s, allowed_operations, None)):
                    ops_set.add(str(o))

            result["taxonomic_parent"] = taxonomic_parent_val
            result["legal_constraint"] = legal_constraint_val
            result["allowed_operations"] = sorted(ops_set)
            result["matching_entities"]["count"] = len(matching_uris)
            # Sample BSMs
            sample_bsms = []
            for uri in matching_uris[:10]:
                for _, _, o in kg.g.triples((uri, URIRef(PLN_NS + "bsm"), None)):
                    sample_bsms.append(str(o))
                    break
            result["matching_entities"]["sample_bsms"] = sample_bsms

            # Encoding bridges from code_sets
            try:
                from app.modules.schema.encodings.code_sets import (
                    DLBM_TO_DLMC, DLBM_TO_ZONE_TYPE, DLBM_TO_PLANNING_ZONE,
                    DLBM_TO_PRIMARY_ZONE, DLBM_TO_GHYTBM,
                )
                # Find DLBM for this label
                for dlbm, dlmc in DLBM_TO_DLMC.items():
                    if dlmc == entity_label:
                        result["encoding_bridges"]["dlbm"] = dlbm
                        result["encoding_bridges"]["dlmc"] = dlmc
                        result["encoding_bridges"]["zone_type"] = DLBM_TO_ZONE_TYPE.get(dlbm, "")
                        result["encoding_bridges"]["planning_zone"] = DLBM_TO_PLANNING_ZONE.get(dlbm, "")
                        result["encoding_bridges"]["primary_zone"] = DLBM_TO_PRIMARY_ZONE.get(dlbm, "")
                        result["encoding_bridges"]["ghytbm"] = DLBM_TO_GHYTBM.get(dlbm, "")
                        break
            except Exception:
                pass

            # If no taxonomic_parent from KG, derive from code_sets
            if not result["taxonomic_parent"] and result["encoding_bridges"].get("zone_type"):
                result["taxonomic_parent"] = result["encoding_bridges"]["zone_type"]

        # If entity_type provided, get type-level info
        if entity_type and not entity_label and not bsm:
            # Get allowed_operations from allowed_operations.yaml by planning_zone
            try:
                from app.modules.schema.encodings.dicts.loader import get_center
                d = get_center().get("allowed_operations").raw
                # For Zone types, map type name to constraint
                if entity_type == "Zone":
                    result["allowed_operations"] = []
                    result["legal_constraint"] = "varies by zone type"
                result["note"] = f"Entity type '{entity_type}' - semantic info varies per instance"
            except Exception:
                pass

        # Enrich with allowed_operations.yaml note
        try:
            from app.modules.schema.encodings.dicts.loader import get_center
            d = get_center().get("allowed_operations").raw
            label = entity_label or result.get("encoding_bridges", {}).get("dlmc", "")
            # Check by_planning_zone
            pz = result.get("encoding_bridges", {}).get("planning_zone", "")
            if pz:
                entry = d.get("by_planning_zone", {}).get(pz)
                if entry:
                    result["allowed_operations_note"] = entry.get("note", "")
                    if not result["allowed_operations"]:
                        result["allowed_operations"] = entry.get("operations", [])
        except Exception:
            pass

        return result
    except Exception as e:
        logger.error("get_entity_semantics failed: %s", e)
        return {"error": str(e), "query_label": entity_label}


__all__ = [
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "get_entity_by_bsm", "get_parcels_by_planning_zone",
    "get_l4_derived_from_l1", "get_village_constraint_coverage",
    "get_parcels_semantic_list", "get_parcel_detail_semantic",
    "get_parcel_neighbors_semantic", "get_facilities_semantic_list",
    "get_road_network_semantic", "get_designated_zones_semantic",
    "get_entity_semantics",
    "TOOL_META_SEMANTIC",
]