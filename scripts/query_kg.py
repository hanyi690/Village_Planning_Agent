"""Standalone KG query script for spatial cognition of villages.

Builds the KG from real GIS data, then executes a named SPARQL/semantic query.
Outputs human-readable results — never reads raw GIS data directly.

Usage:
    python scripts/query_kg.py --list-templates
    python scripts/query_kg.py --template count_entity_types
    python scripts/query_kg.py --template get_village_anchors
    python scripts/query_kg.py --template count_by_zone_type
    python scripts/query_kg.py --template get_village_parcels
    python scripts/query_kg.py --template get_facility_locations
    python scripts/query_kg.py --template get_road_network
    python scripts/query_kg.py --template get_water_bodies
    python scripts/query_kg.py --template get_designated_zones
    python scripts/query_kg.py --template get_parcel_neighbors --params '{"bsm": "..."}'
    python scripts/query_kg.py --template get_parcel_detail --params '{"bsm_val": "..."}'
    python scripts/query_kg.py --template get_parcels_by_zone_type --params '{"zone_type_val": "农业用地"}'
    python scripts/query_kg.py --template count_by_vne
    python scripts/query_kg.py --template count_by_planning_zone
    python scripts/query_kg.py --template get_terrain_profile
    python scripts/query_kg.py --template get_adjacent_parcels
    python scripts/query_kg.py --template get_constraint_coverage
    python scripts/query_kg.py --template get_parcels_by_dlbm --params '{"dlbm_val": "0101"}'
    python scripts/query_kg.py --template get_parcels_near_point --params '{"min_lon":116.0,"max_lon":116.1,"min_lat":24.8,"max_lat":24.9}'
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

_CACHE_DIR = Path(__file__).resolve().parent / ".kg_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(village_name: str) -> Path:
    return _CACHE_DIR / f"{village_name}.ttl"


def _constraint_cache_path(village_name: str) -> Path:
    return _CACHE_DIR / f"{village_name}_constraints.json"


def _load_kg(village_name: str = "jintian", use_cache: bool = True):
    """Load VillageBundle, compute relations, build KG Layer 1+2.
    
    Caches serialized KG to .ttl file for fast reload on subsequent queries.
    Constraint index is serialized separately to avoid redundant DataCatalog loading.
    """
    from app.modules.kg.builder import PlanningKG

    cache_path = _cache_path(village_name)
    constraint_cache = _constraint_cache_path(village_name)

    if use_cache and cache_path.exists():
        t0 = time.time()
        ttl = cache_path.read_text(encoding="utf-8")
        kg = PlanningKG.from_turtle(ttl, village_name=village_name)
        # Rebuild constraint_index from lightweight cache
        if constraint_cache.exists():
            try:
                import json
                from app.modules.spatial_ops.bridge import ConstraintIndex
                import geopandas as gpd
                from shapely.geometry import shape
                cdata = json.loads(constraint_cache.read_text(encoding="utf-8"))
                if cdata.get("rows"):
                    gdf = gpd.GeoDataFrame(cdata["rows"], crs="EPSG:4326")
                    kg._constraint_index = ConstraintIndex(gdf)
            except Exception:
                pass
        t1 = time.time()
        print(f"[query_kg] KG loaded from cache: {kg.get_parcel_count()} parcels, "
              f"{kg.get_triple_count()} triples ({t1-t0:.1f}s)", file=sys.stderr)
        return kg

    from app.modules.data import DataCatalog
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.spatial_ops.bridge import build_constraint_index, compute_water_overlap

    print(f"[query_kg] Loading village bundle: {village_name}...", file=sys.stderr)
    t0 = time.time()
    catalog = DataCatalog()
    bundle = catalog.load_village_bundle(village_name)
    t1 = time.time()
    print(f"[query_kg] Bundle loaded: {len(bundle.polygons.landuse_current)} parcels, {t1-t0:.1f}s", file=sys.stderr)

    print(f"[query_kg] Computing parcel relations...", file=sys.stderr)
    parcel_relations = compute_parcel_relations(
        bundle.polygons.landuse_current,
        roads=bundle.lines.roads_current,
    )
    t2 = time.time()
    print(f"[query_kg] Relations: {len(parcel_relations.touches)} touches, "
          f"{len(parcel_relations.nearby)} nearby, "
          f"{len(parcel_relations.connected)} connected ({t2-t1:.1f}s)", file=sys.stderr)

    print(f"[query_kg] Computing water overlap...", file=sys.stderr)
    water_overlap = compute_water_overlap(
        bundle.polygons.water_bodies,
        bundle.polygons.landuse_current,
    )

    print(f"[query_kg] Building constraint index...", file=sys.stderr)
    constraint_index = build_constraint_index(bundle)

    print(f"[query_kg] Building KG...", file=sys.stderr)
    kg = PlanningKG(village_name=village_name)
    kg.build_from_bundle(
        bundle=bundle,
        parcel_relations=parcel_relations,
        constraint_index=constraint_index,
        water_overlap=water_overlap,
    )
    t3 = time.time()
    print(f"[query_kg] KG built: {kg.get_parcel_count()} parcels, "
          f"{kg.get_triple_count()} triples ({t3-t2:.1f}s)", file=sys.stderr)

    if use_cache:
        ttl = kg.to_turtle()
        cache_path.write_text(ttl, encoding="utf-8")
        # Cache constraint index metadata separately
        if constraint_index is not None:
            try:
                import json
                gdf = constraint_index._gdf
                if gdf is not None:
                    rows = gdf[["bsm", "constraint_type", "geometry"]].copy()
                    rows["geometry_wkt"] = rows["geometry"].apply(lambda g: g.wkt if g is not None else "")
                    del rows["geometry"]
                    constraint_cache.write_text(
                        json.dumps({"rows": rows.to_dict(orient="records")}, ensure_ascii=False),
                        encoding="utf-8",
                    )
            except Exception:
                pass
        print(f"[query_kg] KG cached to {cache_path}", file=sys.stderr)

    return kg


def _format_value(v: Any) -> str:
    if v is None:
        return "-"
    return str(v)


def _print_table(rows: List[Dict[str, Any]], title: str = ""):
    if not rows:
        print(f"\n{'='*60}\n  {title}\n{'='*60}\n  (空结果)")
        return
    if title:
        print(f"\n{'='*60}\n  {title} ({len(rows)} 条)\n{'='*60}")
    keys = list(rows[0].keys())
    col_widths = {k: max(len(k), max((len(str(r.get(k, ""))) for r in rows), default=0)) for k in keys}
    total_width = sum(col_widths.values()) + len(keys) * 3 + 1
    header = "| " + " | ".join(k.ljust(col_widths[k]) for k in keys) + " |"
    sep = "|" + "-" * (total_width - 2) + "|"
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        vals = " | ".join(_format_value(r.get(k, "")).ljust(col_widths[k]) for k in keys)
        print(f"| {vals} |")
    print(sep)


def _print_semantic(rows: List[Dict[str, Any]], title: str = ""):
    if not rows:
        print(f"\n{'='*60}\n  {title}\n{'='*60}\n  (空结果)")
        return
    if title:
        print(f"\n{'='*60}\n  {title} ({len(rows)} 条)\n{'='*60}")
    for i, r in enumerate(rows, 1):
        desc = r.get("description", "")
        if desc:
            print(f"  {i}. {desc}")
        else:
            print(f"  {i}. {json.dumps(r, ensure_ascii=False, indent=2)}")


def _print_raw(rows: List[Dict[str, Any]], title: str = ""):
    if not rows:
        print(f"\n{'='*60}\n  {title}\n{'='*60}\n  (空结果)")
        return
    if title:
        print(f"\n{'='*60}\n  {title} ({len(rows)} 条)\n{'='*60}")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def _print_adjacency(adj: Dict[str, set], title: str = ""):
    if not adj:
        print(f"\n{'='*60}\n  {title}\n{'='*60}\n  (空结果)")
        return
    if title:
        print(f"\n{'='*60}\n  {title}: {len(adj)} 个地块, {sum(len(v) for v in adj.values())} 条边\n{'='*60}")
    for bsm, neighbors in sorted(adj.items(), key=lambda x: len(x[1]), reverse=True)[:30]:
        n_str = ", ".join(sorted(neighbors)[:10])
        extra = f"... +{len(neighbors)-10}" if len(neighbors) > 10 else ""
        print(f"  BSM {bsm} <-> [{n_str}{extra}]")


def _print_constraint_coverage(rows: List[Dict[str, Any]], title: str = ""):
    if not rows:
        print(f"\n{'='*60}\n  {title}\n{'='*60}\n  (空结果 — 无约束重叠)")
        return
    if title:
        print(f"\n{'='*60}\n  {title}: {len(rows)} 个地块受约束\n{'='*60}")
    for r in rows:
        bsm = r.get("bsm", "")
        dlbm = r.get("dlbm", "")
        zt = r.get("zone_type", "")
        area = r.get("area_ha", "")
        constraints = r.get("constraints", [])
        c_str = "; ".join(
            f"{c.get('constraint_type','')} ({c.get('overlap_pct',0):.1f}%)"
            for c in constraints
        )
        print(f"  BSM {bsm} | DLBM {dlbm} | {zt} | {area}ha | 约束: {c_str}")


def main():
    parser = argparse.ArgumentParser(description="Query the village planning KG")
    parser.add_argument("--template", type=str, default="",
                        help="Query template name (see --list-templates)")
    parser.add_argument("--params", type=str, default="{}",
                        help="JSON string of query parameters, e.g. '{\"bsm_val\": \"P001\"}'")
    parser.add_argument("--village", type=str, default="jintian",
                        help="Village name (default: jintian)")
    parser.add_argument("--list-templates", action="store_true",
                        help="List all available query templates")
    parser.add_argument("--raw", action="store_true",
                        help="Output raw JSON instead of formatted table")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip KG cache and rebuild from scratch")
    args = parser.parse_args()

    if args.list_templates:
        from app.modules.kg.queries.sparql import QUERY_TEMPLATES, SEMANTIC_QUERIES
        print(f"\n{'='*60}\n  SPARQL 查询模板\n{'='*60}")
        for name in sorted(QUERY_TEMPLATES.keys()):
            print(f"  {name}")
        print(f"\n{'='*60}\n  语义查询（返回人类可读描述）\n{'='*60}")
        for name in sorted(SEMANTIC_QUERIES.keys()):
            print(f"  {name}")
        print(f"\n{'='*60}\n  实例方法（额外查询）\n{'='*60}")
        print(f"  get_adjacency_map")
        print(f"  get_constraint_coverage")
        print(f"  get_entity_context")
        print(f"  get_entity_relations")
        print(f"  get_parcel_semantic_context")
        print(f"  get_village_semantic_summary")
        return

    if not args.template:
        parser.print_help()
        sys.exit(1)

    params = json.loads(args.params) if args.params else {}

    kg = _load_kg(args.village, use_cache=not args.no_cache)

    print(f"\n{'#'*70}")
    print(f"#  查询: {args.template}")
    print(f"#  参数: {params}")
    print(f"{'#'*70}")

    template = args.template

    from app.modules.kg.queries.sparql import QUERY_TEMPLATES, SEMANTIC_QUERIES

    if template in SEMANTIC_QUERIES:
        from app.modules.kg.queries import query_kg as qk
        rows = qk(kg, template, **params)
        _print_semantic(rows, title=template)
    elif template in QUERY_TEMPLATES:
        from app.modules.kg.queries import query_kg as qk
        rows = qk(kg, template, **params)
        if args.raw:
            _print_raw(rows, title=template)
        else:
            _print_table(rows, title=template)
    elif template == "get_adjacency_map":
        adj = kg.get_adjacency_map()
        _print_adjacency(adj, title="地块邻接关系")
    elif template == "get_constraint_coverage":
        rows = kg.get_constraint_coverage()
        _print_constraint_coverage(rows, title="约束覆盖")
    elif template == "get_entity_context":
        from app.modules.kg.queries import get_entity_context
        result = get_entity_context(kg, params.get("entity_uri", ""))
        _print_raw([result] if isinstance(result, dict) else result, title="实体上下文")
    elif template == "get_entity_relations":
        from app.modules.kg.queries import get_entity_relations
        result = get_entity_relations(kg, params.get("entity_uri", ""))
        _print_raw(result, title="实体关系")
    elif template == "get_parcel_semantic_context":
        from app.modules.kg.queries import get_parcel_semantic_context
        result = get_parcel_semantic_context(kg, params.get("bsm", ""))
        _print_raw([result] if isinstance(result, dict) else result, title="地块语义上下文")
    elif template == "get_village_semantic_summary":
        from app.modules.kg.queries import get_village_semantic_summary
        result = get_village_semantic_summary(kg)
        print(f"\n{'='*60}\n  村庄语义摘要\n{'='*60}")
        if isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, dict):
                    print(f"  {k}:")
                    for sk, sv in sorted(v.items()):
                        print(f"    {sk}: {sv}")
                elif isinstance(v, list):
                    print(f"  {k}: {', '.join(str(x) for x in v)}")
                else:
                    print(f"  {k}: {v}")
        else:
            print(result)
    elif template == "get_parcels_by_planning_zone":
        from app.modules.kg.queries import get_parcels_by_planning_zone
        rows = get_parcels_by_planning_zone(kg, params.get("planning_zone", ""))
        _print_table(rows, title=f"规划分区: {params.get('planning_zone', '')}")
    elif template == "get_entity_by_bsm":
        from app.modules.kg.queries import get_entity_by_bsm
        result = get_entity_by_bsm(kg, params.get("bsm", ""))
        _print_raw([result] if isinstance(result, dict) else result, title=f"实体 BSM: {params.get('bsm', '')}")
    elif template == "get_l4_derived_from_l1":
        from app.modules.kg.queries import get_l4_derived_from_l1
        rows = get_l4_derived_from_l1(kg, params.get("l1_bsm", ""))
        _print_table(rows, title=f"L4 衍生自 L1: {params.get('l1_bsm', '')}")
    elif template == "get_village_constraint_coverage":
        from app.modules.kg.queries import get_village_constraint_coverage
        rows = get_village_constraint_coverage(kg)
        _print_constraint_coverage(rows, title="村庄约束覆盖")
    else:
        print(f"[query_kg] 未知模板: {template}")
        sys.exit(1)


if __name__ == "__main__":
    main()