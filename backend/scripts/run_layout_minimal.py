"""Minimal LAYOUT pipeline — loads parse_cache, runs MIP allocation, exports results.

Usage: cd backend && python -m scripts.run_layout_minimal [--cache path/to/cache.json]
"""

import asyncio, json, sys, time
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "gis" / "jintian"
PARSE_CACHE_DIR = ROOT / "output" / "parse_cache"
OUTPUT_DIR = ROOT / "output" / "layout_results"


def load_gis_data() -> dict:
    layer_map = {
        "landuse_current_geojson": "current/landuse.geojson",
        "boundary_geojson": "current/boundary.geojson",
        "road_geojson": "current/road.geojson",
        "annotation_geojson": "current/annotation.geojson",
        "construction_boundary_geojson": "planned/construction_zone.geojson",
        "farmland_protection_geojson": "planned/farmland_protection.geojson",
        "ecological_protection_geojson": "planned/ecological_protection.geojson",
        "geological_hazard_geojson": "planned/geological_hazard_points.geojson",
        "historical_protection_geojson": "planned/historical_protection.geojson",
    }
    gis = {}
    for key, rel in layer_map.items():
        fp = DATA_DIR / rel
        if fp.exists():
            with open(str(fp), "r", encoding="utf-8") as f:
                gis[key] = json.load(f)
    print(f"  GIS: {len(gis)} layers loaded", flush=True)
    return gis


def load_parse_cache(path: Path) -> Optional[dict]:
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if "planning_intent" not in data:
        print(f"  [CACHE] Missing planning_intent", flush=True)
        return None
    return data


def _reconstruct_zone_targets(targets_data: list) -> list:
    """Convert cached ZoneTarget dicts back to typed objects."""
    if not targets_data:
        return []
    from app.modules.schema.contracts.parse_contracts import ZoneTarget
    result = []
    for t in targets_data:
        if isinstance(t, dict):
            result.append(ZoneTarget(**t))
        else:
            result.append(t)
    return result


def _unpack_planning_intent(pi: dict) -> dict:
    return {
        "zone_targets": _reconstruct_zone_targets(pi.get("zone_targets", [])),
        "facilities": pi.get("facilities", []),
        "development_axes": pi.get("development_axes", []),
        "road_targets": pi.get("road_targets", []),
        "village_name": pi.get("village_name", ""),
    }


async def main(cache_path: Optional[Path] = None):
    print("=" * 60, flush=True)
    print("STEP 0: Load GIS data", flush=True)
    print("=" * 60, flush=True)
    gis_data = load_gis_data()
    landuse = gis_data.get("landuse_current_geojson", {})

    print("\n" + "=" * 60, flush=True)
    print("STEP 1: Load PARSE cache", flush=True)
    print("=" * 60, flush=True)
    if not cache_path:
        caches = sorted(PARSE_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not caches:
            print("  [ERROR] No parse cache found", flush=True)
            return
        cache_path = caches[0]
    parse_data = load_parse_cache(cache_path)
    if parse_data is None:
        print(f"  [ERROR] Invalid cache: {cache_path}", flush=True)
        return
    print(f"  Loaded: {cache_path.name}", flush=True)
    planning_intent_data = parse_data.get("planning_intent", {})
    intent = _unpack_planning_intent(planning_intent_data)
    zone_targets = intent["zone_targets"]
    print(f"  Zone targets: {len(zone_targets)}", flush=True)
    for zt in zone_targets:
        print(f"    {zt.land_use}: {zt.area_ratio:.1%} (candidates={len(getattr(zt, 'candidate_bsms', []) or [])})", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("STEP 2: Build KG", flush=True)
    print("=" * 60, flush=True)
    from app.modules.kg.manager import get_kg_manager
    from app.modules.data.catalog import DataCatalog
    from app.modules.kg.builder import PlanningKG
    manager = get_kg_manager()
    bundle = None
    try:
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle("jintian")
        print(f"  Bundle loaded", flush=True)
    except Exception as e:
        print(f"  Bundle load skipped: {e}", flush=True)
    kg, cache_hit = manager.get_or_build_layer1(
        "金田村", bundle=bundle, landuse_geojson=landuse, gis_data=gis_data
    )
    annotations = gis_data.get("annotation_geojson", {}).get("features", [])
    roads = gis_data.get("road_geojson", {}).get("features", [])
    if annotations:
        kg.add_annotations(annotations)
    if roads:
        kg.add_roads(roads)
    if gis_data:
        kg.add_protection_zones(gis_data)
    manager.register_session("layout_pipeline", kg)
    print(f"  KG: {kg.get_triple_count()} triples, cache_hit={cache_hit}", flush=True)

    # Build target map for MIP
    target_map = {}
    for zt in zone_targets:
        name = zt.land_use
        ratio = getattr(zt, "area_ratio", 0) or 0
        area_ha = getattr(zt, "area_ha", 0) or 0
        if area_ha > 0:
            target_map[name] = area_ha
        elif ratio > 0:
            total_ha = sum(
                float(f.get("properties", {}).get("area_ha", f.get("properties", {}).get("面积", 0)) or 0)
                for f in landuse.get("features", [])
            )
            target_map[name] = total_ha * ratio
    print(f"\n  Allocation targets: {json.dumps(target_map, ensure_ascii=False, indent=2)}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("STEP 3: MIP Allocation", flush=True)
    print("=" * 60, flush=True)
    from app.tools.gis._generation.optimizer.mip_allocator import MIPZoneAllocator
    allocator = MIPZoneAllocator()
    allocated_geojson, mip_trace = allocator.solve(
        landuse_geojson=landuse,
        targets=target_map,
        zone_targets=zone_targets,
        kg=kg,
    )
    n_allocated = len(allocated_geojson.get("features", []))
    print(f"  Allocated: {n_allocated} features", flush=True)
    for feat in allocated_geojson.get("features", [])[:5]:
        props = feat.get("properties", {})
        print(f"    BSM={props.get('BSM', '?')} zone={props.get('planning_zone', '?')} dlbm={props.get('DLBM', '?')}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("STEP 4: Export results", flush=True)
    print("=" * 60, flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    geojson_path = OUTPUT_DIR / f"jintian_allocated_{ts}.json"
    geojson_path.write_text(
        json.dumps(allocated_geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  GeoJSON: {geojson_path}", flush=True)

    # Stats
    zones = {}
    for feat in allocated_geojson.get("features", []):
        z = feat.get("properties", {}).get("planning_zone", "unassigned")
        dlbm = str(feat.get("properties", {}).get("DLBM", ""))
        area = float(feat.get("properties", {}).get("area_ha", 0))
        zones.setdefault(z, {"count": 0, "area_ha": 0.0, "dlbms": set()})
        zones[z]["count"] += 1
        zones[z]["area_ha"] += area
        zones[z]["dlbms"].add(dlbm)
    print(f"\n  Allocation summary:", flush=True)
    for z, info in sorted(zones.items()):
        dlbm_str = ", ".join(sorted(info["dlbms"]))
        print(f"    {z}: {info['count']} parcels, {info['area_ha']:.1f}ha [{dlbm_str}]", flush=True)

    trace_path = OUTPUT_DIR / f"jintian_mip_trace_{ts}.json"
    trace_path.write_text(json.dumps(mip_trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  Trace: {trace_path}", flush=True)
    print(f"\nDone! Results in {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=str, default="", help="Path to parse cache JSON")
    args = parser.parse_args()
    cache = Path(args.cache) if args.cache else None
    asyncio.run(main(cache_path=cache))
