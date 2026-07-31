"""
kg_tool_cli.py — Agent A (BLIND KG) 工具 CLI
==============================================
36 个 KG 查询工具通过此 CLI 暴露给 LLM 子代理。

用法:
    python -m scripts.kg_validation.kg_tool_cli <tool> [args...]

示例:
    python -m scripts.kg_validation.kg_tool_cli get_village_semantic_summary
    python -m scripts.kg_validation.kg_tool_cli query_kg get_village_parcels
    python -m scripts.kg_validation.kg_tool_cli get_facilities_semantic_list
    python -m scripts.kg_validation.kg_tool_cli get_parcels_by_bsm_list P001,P002,P003

输出: JSON 到 stdout，错误返回 {"error": "..."}
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 路径 setup ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

CACHE_FILE = Path(__file__).parent / ".kg_cache.pkl"
MAX_LIST_ELEMENTS = 10
TOOL_TIMEOUT_SEC = 30


# ── KG 构建（带 pickle 缓存）──────────────────────────────────────────────────
def _build_kg():
    from app.modules.data.ingest import ingest_current_landuse, ingest_feature
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import KGBuilder

    JINTIAN_DATA = PROJECT_ROOT / "data" / "gis" / "jintian"
    bundle = VillageBundle(village_name="jintian")

    landuse_path = JINTIAN_DATA / "current" / "landuse.geojson"
    parcels, _ = ingest_current_landuse(str(landuse_path))
    for p in parcels:
        bundle.add(p)

    road_path = JINTIAN_DATA / "current" / "road.geojson"
    roads, _ = ingest_feature(str(road_path), "current_road")
    for r in roads:
        bundle.add(r)

    ann_path = JINTIAN_DATA / "current" / "annotation.geojson"
    anns, _ = ingest_feature(str(ann_path), "current_annotation")
    for a in anns:
        bundle.add(a)

    for feature_type, filename in [
        ("farmland_protection", "farmland_protection.geojson"),
        ("ecological_redline", "ecological_protection.geojson"),
        ("historical_protection", "historical_protection.geojson"),
    ]:
        fp = JINTIAN_DATA / "planned" / filename
        if fp.exists():
            feats, _ = ingest_feature(str(fp), feature_type)
            for f in feats:
                bundle.add(f)

    boundary_path = JINTIAN_DATA / "current" / "boundary.geojson"
    boundary, _ = ingest_feature(str(boundary_path), "admin_area")
    for b in boundary:
        bundle.add(b)

    rel = compute_parcel_relations(
        bundle.polygons.get("landuse_current"),
        roads=bundle.lines.get("roads_current"),
    )
    ci = build_constraint_index(bundle)
    kg = KGBuilder.build("jintian", bundle, parcel_relations=rel, constraint_index=ci)
    return kg


def get_cached_kg():
    if CACHE_FILE.exists():
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            age_hours = (time.time() - mtime) / 3600
            if age_hours < 24:
                with open(CACHE_FILE, "rb") as f:
                    kg = pickle.load(f)
                print(f"[kg_tool_cli] Loaded KG from cache: {kg.get_triple_count()} triples, {kg.get_parcel_count()} parcels", file=sys.stderr)
                return kg
        except Exception as e:
            print(f"[kg_tool_cli] Cache load failed ({e}), rebuilding...", file=sys.stderr)

    print(f"[kg_tool_cli] Building KG (no cache or stale)...", file=sys.stderr)
    t0 = time.time()
    kg = _build_kg()
    print(f"[kg_tool_cli] KG built in {time.time()-t0:.1f}s: {kg.get_triple_count()} triples, {kg.get_parcel_count()} parcels", file=sys.stderr)

    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(kg, f)
        print(f"[kg_tool_cli] KG cached to {CACHE_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"[kg_tool_cli] Cache write failed: {e}", file=sys.stderr)

    return kg


# ── 工具实现 ─────────────────────────────────────────────────────────────────

def _dualpayload_to_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _dualpayload_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dualpayload_to_dict(x) for x in obj]
    try:
        if hasattr(obj, "to_dict"):
            return _dualpayload_to_dict(obj.to_dict())
        if hasattr(obj, "__dict__"):
            d = {k: _dualpayload_to_dict(v) for k, v in obj.__dict__.items()}
            return d
    except Exception:
        pass
    return obj


def _json_serializable(obj: Any) -> Any:
    """Convert any object to JSON-serializable Python type."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {k: _json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        result = [_json_serializable(x) for x in obj]
        return result
    if isinstance(obj, set):
        return sorted(_json_serializable(x) for x in obj)
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def _truncate_list(result: Any, max_items: int = MAX_LIST_ELEMENTS) -> Any:
    """Truncate long lists to max_items + total_count."""
    if isinstance(result, list):
        total = len(result)
        truncated = result[:max_items]
        if total > max_items:
            return {"_truncated": True, "total_count": total, "items": _json_serializable(truncated)}
        return _json_serializable(truncated)
    if isinstance(result, dict):
        return {k: _truncate_list(v, max_items) for k, v in result.items()}
    return _json_serializable(result)


def _run_tool(tool_name: str, args: List[str]) -> Dict[str, Any]:
    """Dispatch to the appropriate tool and return JSON-serializable result."""
    t0 = time.time()
    kg = get_cached_kg()

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    if tool_name == "get_village_cognition":
        from app.modules.kg.queries.cognition import get_village_cognition
        result = get_village_cognition(kg, village_name="jintian")
        result = _dualpayload_to_dict(result)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_village_semantic_summary":
        from app.modules.kg.queries.semantic import get_village_semantic_summary
        result = get_village_semantic_summary(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_layer_group_semantics":
        from app.modules.kg.queries.cognition import get_layer_group_semantics
        group = args[0] if args else None
        result = get_layer_group_semantics(kg, group=group)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_village_constraint_coverage":
        from app.modules.kg.queries.semantic import get_village_constraint_coverage
        result = get_village_constraint_coverage(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── ENTITY_DETAIL ──────────────────────────────────────────────────────────
    if tool_name == "get_entity_context":
        entity_uri = args[0] if args else ""
        from app.modules.kg.queries.semantic import get_entity_context
        result = get_entity_context(kg, entity_uri)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_entity_relations":
        entity_uri = args[0] if args else ""
        from app.modules.kg.queries.semantic import get_entity_relations
        result = get_entity_relations(kg, entity_uri)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_entity_semantics":
        entity_label = args[0] if args else "地块"
        from app.modules.kg.queries.semantic import get_entity_semantics
        result = get_entity_semantics(kg, entity_label=entity_label)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_parcel_semantic_context":
        bsm = args[0] if args else ""
        from app.modules.kg.queries.semantic import get_parcel_semantic_context
        result = get_parcel_semantic_context(kg, bsm)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_entity_by_bsm":
        bsm = args[0] if args else ""
        entity_type = args[1] if len(args) > 1 else None
        from app.modules.kg.queries.semantic import get_entity_by_bsm
        result = get_entity_by_bsm(kg, bsm, entity_type=entity_type)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── LIST_SEMANTIC ──────────────────────────────────────────────────────────
    if tool_name == "get_parcels_semantic_list":
        from app.modules.kg.queries.semantic import get_parcels_semantic_list
        result = get_parcels_semantic_list(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result, max_items=5), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_parcel_detail_semantic":
        bsm = args[0] if args else ""
        from app.modules.kg.queries.semantic import get_parcel_detail_semantic
        result = get_parcel_detail_semantic(kg, bsm)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_parcel_neighbors_semantic":
        bsm = args[0] if args else ""
        from app.modules.kg.queries.semantic import get_parcel_neighbors_semantic
        result = get_parcel_neighbors_semantic(kg, bsm)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_facilities_semantic_list":
        from app.modules.kg.queries.semantic import get_facilities_semantic_list
        result = get_facilities_semantic_list(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_road_network_semantic":
        from app.modules.kg.queries.semantic import get_road_network_semantic
        result = get_road_network_semantic(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_designated_zones_semantic":
        from app.modules.kg.queries.semantic import get_designated_zones_semantic
        result = get_designated_zones_semantic(kg)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── SPARQL ─────────────────────────────────────────────────────────────────
    if tool_name == "query_kg":
        template_name = args[0] if args else ""
        from app.modules.kg.queries.sparql import query_kg as _q
        result = _q(kg, template_name)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── RAW_GRAPH ──────────────────────────────────────────────────────────────
    if tool_name == "kg_query":
        sparql = args[0] if args else ""
        result = kg.query(sparql)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "kg_predicate_objects":
        uri = args[0] if args else ""
        from rdflib import URIRef
        u = URIRef(uri) if uri.startswith("http") else URIRef(f"http://village-planning.org/ontology#{uri}")
        results = list(kg.g.predicate_objects(u))
        result = [{"predicate": str(p), "object": str(o)} for p, o in results[:20]]
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "kg_triples":
        s = args[0] if len(args) > 0 else None
        p = args[1] if len(args) > 1 else None
        o = args[2] if len(args) > 2 else None
        if s and not s.startswith("http"):
            s = f"http://village-planning.org/ontology#{s}" if s else None
        if p and not p.startswith("http"):
            p = f"http://village-planning.org/ontology#{p}" if p else None
        triple = (s, p, o)
        results = list(kg.g.triples(triple))[:20]
        result = [{"subject": str(s), "predicate": str(p), "object": str(o)} for s, p, o in results]
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "kg_to_turtle":
        result = kg.to_turtle()
        elapsed = time.time() - t0
        return {"result": result[:2000] if result else "", "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── INSTANCE ───────────────────────────────────────────────────────────────
    if tool_name == "get_parcel_count":
        result = kg.get_parcel_count()
        elapsed = time.time() - t0
        return {"result": result, "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_triple_count":
        result = kg.get_triple_count()
        elapsed = time.time() - t0
        return {"result": result, "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_adjacency_map":
        result = kg.get_adjacency_map()
        elapsed = time.time() - t0
        return {"result": _truncate_list({k: list(v) for k, v in list(result.items())[:20]}, max_items=20), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── TOPOLOGY ───────────────────────────────────────────────────────────────
    if tool_name == "get_parcels_within_distance_of_entity":
        entity_uri = args[0] if args else ""
        max_distance_m = float(args[1]) if len(args) > 1 else 200
        from app.modules.kg.queries.sparql import get_parcels_within_distance_of_entity
        result = get_parcels_within_distance_of_entity(kg, entity_uri, max_distance_m=max_distance_m)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_adjacent_parcels_with_length":
        bsm = args[0] if args else ""
        from app.modules.kg.queries.sparql import get_adjacent_parcels_with_length
        result = get_adjacent_parcels_with_length(kg, bsm)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_connected_parcels":
        parcel_uri = args[0] if args else ""
        from app.modules.kg.queries.sparql import get_connected_parcels
        result = get_connected_parcels(kg, parcel_uri)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_parcels_by_bsm_list":
        bsms = args[0].split(",") if args else []
        from app.modules.kg.queries.sparql import get_parcels_by_bsm_list
        result = get_parcels_by_bsm_list(kg, bsms)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── L4 ─────────────────────────────────────────────────────────────────────
    if tool_name == "get_effective_land_use":
        bsm = args[0] if args else ""
        version = args[1] if len(args) > 1 else "current"
        from app.modules.kg.queries.sparql import get_effective_land_use
        result = get_effective_land_use(kg, bsm, version=version)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_effective_area_ha":
        bsm = args[0] if args else ""
        version = args[1] if len(args) > 1 else "current"
        from app.modules.kg.queries.sparql import get_effective_area_ha
        result = get_effective_area_ha(kg, bsm, version=version)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_plan_changes":
        version = args[0] if args else "current"
        from app.modules.kg.queries.sparql import get_plan_changes
        result = get_plan_changes(kg, version=version)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "get_planned_parcels_in_zone":
        zone_type = args[0] if args else ""
        version = args[1] if len(args) > 1 else "current"
        from app.modules.kg.queries.sparql import get_planned_parcels_in_zone
        result = get_planned_parcels_in_zone(kg, zone_type, version=version)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "check_constraint_violations":
        version = args[0] if args else "current"
        from app.modules.kg.queries.sparql import check_constraint_violations
        result = check_constraint_violations(kg, version=version)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    if tool_name == "compare_versions":
        version_a = args[0] if args else "current"
        version_b = args[1] if len(args) > 1 else "planned"
        from app.modules.kg.queries.sparql import compare_versions
        result = compare_versions(kg, version_a, version_b)
        elapsed = time.time() - t0
        return {"result": _truncate_list(result), "tool": tool_name, "elapsed_ms": round(elapsed * 1000, 1)}

    # ── UNKNOWN ────────────────────────────────────────────────────────────────
    available = [
        "get_village_cognition", "get_village_semantic_summary", "get_layer_group_semantics",
        "get_village_constraint_coverage", "get_entity_context", "get_entity_relations",
        "get_entity_semantics", "get_parcel_semantic_context", "get_entity_by_bsm",
        "get_parcels_semantic_list", "get_parcel_detail_semantic", "get_parcel_neighbors_semantic",
        "get_facilities_semantic_list", "get_road_network_semantic", "get_designated_zones_semantic",
        "query_kg", "kg_query", "kg_predicate_objects", "kg_triples", "kg_to_turtle",
        "get_parcel_count", "get_triple_count", "get_adjacency_map",
        "get_parcels_within_distance_of_entity", "get_adjacent_parcels_with_length",
        "get_connected_parcels", "get_parcels_by_bsm_list",
        "get_effective_land_use", "get_effective_area_ha", "get_plan_changes",
        "get_planned_parcels_in_zone", "check_constraint_violations", "compare_versions",
    ]
    return {
        "error": f"Unknown tool: {tool_name}",
        "available_tools": available,
        "tool": tool_name,
        "elapsed_ms": 0,
    }


# ── CLI 入口 ─────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage: python -m scripts.kg_validation.kg_tool_cli <tool> [args...]",
            "example": "python -m scripts.kg_validation.kg_tool_cli get_village_semantic_summary",
            "example2": "python -m scripts.kg_validation.kg_tool_cli query_kg get_village_parcels",
            "example3": "python -m scripts.kg_validation.kg_tool_cli get_facilities_semantic_list",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    tool_name = sys.argv[1]
    args = sys.argv[2:]

    try:
        result = _run_tool(tool_name, args)
    except Exception as e:
        result = {"error": str(e), "tool": tool_name, "elapsed_ms": 0}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
