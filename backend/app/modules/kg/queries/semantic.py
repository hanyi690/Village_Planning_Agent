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
from typing import Any, Dict, List, Optional

from rdflib import RDF as RDF_TERM, URIRef

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
    "NaturalSettlement": "自然村",
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
        if bsm:
            parts.append(bsm)
        if dlbm:
            parts.append(f"地类编码{dlbm}")
        if area:
            parts.append(f"面积{area}公顷")
        if zt:
            parts.append(f"({zt})")

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

    elif entity_type == "NaturalSettlement":
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
    "touches": "相邻",
    "nearby": "邻近",
    "connected_via_road": "道路连接",
    "within_zone": "位于",
    "located_in": "位于",
    "designated_as": "被划定为",
    "derived_from": "源自",
    "serves": "服务于",
    "connects": "连接",
    "delineates": "界定了",
    "has_road": "有道路",
    "contains": "包含",
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
    if pred_name in ("touches", "nearby", "connected_via_road"):
        return f"与{obj_short}{pred_cn}"
    if pred_name in ("within_zone", "located_in", "designated_as",
                     "derived_from", "serves", "connects", "delineates",
                     "contains", "relates_to_anchor"):
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
    """Find parcel URI by BSM using SPARQL, with fallback to triple scan."""
    try:
        rows = kg.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            "SELECT ?p WHERE { ?p a pln:Parcel ; pln:bsm ?bsm . }",
        )
        for r in rows:
            uri = r.get("p")
            if uri:
                return _to_uri(uri)
    except Exception:
        pass

    # Fallback: direct triple scan
    try:
        for s, _, o in kg.g.triples((None, None, None)):
            if str(o) == bsm:
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

        result = {
            "village_name": name,
            "parcel_count": entity_counts.get("Parcel", 0),
            "entity_counts": entity_counts,
            "relation_counts": relation_counts,
            "total_triples": len(kg.g),
        }

        memory = _get_memory(kg)
        if memory is not None:
            village_uri = str(PLN_NS + "village")
            if memory.get_entity_semantics(village_uri) is None:
                desc_parts = [f"村庄{name}" if name else "村庄"]
                pcount = entity_counts.get("Parcel", 0)
                rcount = entity_counts.get("Road", 0)
                scount = entity_counts.get("NaturalSettlement", 0)
                fcount = entity_counts.get("Facility", 0)
                if pcount:
                    desc_parts.append(f"共{pcount}个地块")
                if rcount:
                    desc_parts.append(f"{rcount}条道路")
                if scount:
                    desc_parts.append(f"{scount}个自然村")
                if fcount:
                    desc_parts.append(f"{fcount}个设施点")
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


# ── Tool metadata for LLM ──

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
                    "description": "Entity URI (e.g. pln:NaturalSettlement/刘村, or a full URI)",
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
            "description": "Get a human-readable summary of the entire village KG (entity counts, relation counts)",
            "parameters": {},
        },
    },
}


__all__ = [
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "TOOL_META_SEMANTIC",
]