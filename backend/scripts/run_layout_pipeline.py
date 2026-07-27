"""Run full LAYOUT pipeline from cached PARSE output and generate Markdown report + PNG renders.

This pipeline is INDEPENDENT from the PARSE pipeline. It only reads PARSE results
from the cache directory — it never runs PARSE inline. Run run_parse_pipeline.py
first to populate the cache.

Usage:
  cd backend
  # First: run PARSE pipeline to produce cache
  python -m scripts.run_parse_pipeline --source db
  python -m scripts.run_parse_pipeline --source mineru

  # Then: run LAYOUT pipeline (consumes cache)
  python -m scripts.run_layout_pipeline --source db
  python -m scripts.run_layout_pipeline --source mineru
  python -m scripts.run_layout_pipeline --parse-cache output/parse_cache/jintian_db_20260723.json
  python -m scripts.run_layout_pipeline --compare

Reads:
  - data/gis/jintian/current/*.geojson (GIS data)
  - output/parse_cache/{village}_{source}_*.json (PARSE cache)

Writes:
  - output/layout_results/{village}_{date}/report.md (layout report)
  - output/layout_results/{village}_{date}/mip_result.json (MIP allocation results)
  - output/layout_results/{village}_{date}/kg_output.json (KG constraints, adjacency, restrictions, turtle)
  - output/layout_results/{village}_{date}/allocation_result.json (raw allocated GeoJSON + full MIP trace)
  - output/layout_results/{village}_{date}/validation_detail.json (per-round checks, violations, adjustments)
  - output/layout_results/{village}_{date}/pipeline_run.json (timing, source, config, file index)
  - output/layout_results/{village}_{date}/geojson/*.geojson (exported layers)
  - output/layout_results/{village}_{date}/render/*.png (rendered maps)

Features:
  - KG Layer 1 caching via KGManager
  - PARSE cache lookup with source filtering (db/mineru/json/text/auto)
  - MIP allocation with density_hints + adjacency_rules consumption
  - MIP result export (targets/actuals/deviations/metadata)
  - Validation retry loop (max 3 rounds)
  - Multi-layer rendering (planning_zone, comparison, composite)
  - Markdown report with MIP trace, validation results, timing
  - --compare mode: DB vs MinerU layout comparison report
"""

import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "gis" / "jintian"
L3_REPORTS_PATH = (
    PROJECT_ROOT / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
)
PARSE_CACHE_DIR = PROJECT_ROOT / "output" / "parse_cache"
OUTPUT_DIR = PROJECT_ROOT / "output" / "layout_results"

MAX_VALIDATION_ROUNDS = 3


# ── StepTimer utility ──────────────────────────────────────────────


class StepTimer:
    """Context manager that prints step name and elapsed time."""

    def __init__(self, name: str):
        self.name = name
        self.start = None

    def __enter__(self):
        self.start = time.time()
        print(f"\n{'=' * 60}", flush=True)
        print(f">> Step: {self.name}", flush=True)
        print(f"{'=' * 60}", flush=True)
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.start
        print(f"  [{self.name}]: {elapsed:.1f}s", flush=True)


# ── Data loading ───────────────────────────────────────────────────


def load_gis_data() -> Tuple[dict, list, list]:
    """Load all current + planned GeoJSON layers directly from data/gis/jintian."""
    layer_map = {
        "landuse_current_geojson": "current/landuse.geojson",
        "boundary_geojson": "current/boundary.geojson",
        "admin_boundary_line_geojson": "current/admin_boundary_line.geojson",
        "road_geojson": "current/road.geojson",
        "annotation_geojson": "current/annotation.geojson",
        "construction_boundary_geojson": "planned/construction_zone.geojson",
        "farmland_protection_geojson": "planned/farmland_protection.geojson",
        "ecological_protection_geojson": "planned/ecological_protection.geojson",
        "geological_hazard_geojson": "planned/geological_hazard_points.geojson",
        "historical_protection_geojson": "planned/historical_protection.geojson",
    }
    gis_data = {}
    for key, rel_path in layer_map.items():
        fp = DATA_DIR / rel_path
        if fp.exists():
            with open(str(fp), "r", encoding="utf-8") as f:
                gis_data[key] = json.load(f)

    annotations = gis_data.get("annotation_geojson", {"type": "FeatureCollection", "features": []}).get("features", [])
    roads = gis_data.get("road_geojson", {"type": "FeatureCollection", "features": []}).get("features", [])
    print(f"  [GIS] Loaded {len(gis_data)} layers, {len(annotations)} annotations, {len(roads)} roads", flush=True)
    return gis_data, annotations, roads


def load_planning_text() -> str:
    """Load L3 reports as combined planning text."""
    if not L3_REPORTS_PATH.exists():
        print(f"  [TEXT] L3 reports not found at {L3_REPORTS_PATH}", flush=True)
        return ""

    with open(str(L3_REPORTS_PATH), "r", encoding="utf-8") as f:
        data = json.load(f)

    reports = data.get("reports", {})
    if not reports:
        print("  [TEXT] No reports in L3 file", flush=True)
        return ""

    sections = []
    for dim_key, content in reports.items():
        if isinstance(content, dict):
            text = content.get("content", content.get("summary", ""))
        else:
            text = str(content)
        if text:
            sections.append(f"## {dim_key}\n\n{text}")

    combined = "\n\n".join(sections)
    print(f"  [TEXT] Combined planning text: {len(combined)} chars", flush=True)
    return combined


# ── PARSE result caching ───────────────────────────────────────────


def load_parse_cache(cache_path: Optional[Path]) -> Optional[Dict]:
    """Load PARSE results from cache file."""
    if not cache_path or not cache_path.exists():
        print(f"  [CACHE] Cache path not found: {cache_path}", flush=True)
        return None

    try:
        with open(str(cache_path), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [CACHE] Failed to load cache {cache_path.name}: {e}", flush=True)
        return None

    required = ["planning_intent"]
    if not all(k in data for k in required):
        print(f"  [CACHE] Invalid cache file: missing {set(required) - set(data.keys())}", flush=True)
        return None

    print(f"  [CACHE] Loaded PARSE cache: {cache_path.name}", flush=True)
    # Field-level detail for cache quality verification
    intent = data.get("planning_intent", {})
    zt_count = len(intent.get("zone_targets", [])) if isinstance(intent, dict) else 0
    ops_count = len(data.get("operation_sequence", []))
    cs_count = len(data.get("constraint_set", []))
    ve_count = len(data.get("validation_errors", []))
    print(
        f"  [CACHE] Fields: zone_targets={zt_count}, operations={ops_count}, "
        f"constraints={cs_count}, validation_errors={ve_count}",
        flush=True,
    )
    return data


VILLAGE_NAME_ALIASES = {
    "jintian": "金田村",
    "金田村": "金田村",
}


def _resolve_village_names(name: str) -> List[str]:
    """Return both alias forms of a village name for cache lookup."""
    names = {name}
    if name in VILLAGE_NAME_ALIASES:
        names.add(VILLAGE_NAME_ALIASES[name])
    # Reverse lookup
    for k, v in VILLAGE_NAME_ALIASES.items():
        if v == name:
            names.add(k)
    return list(names)


def load_latest_parse_cache(village_name: str, source: Optional[str] = None) -> Optional[Dict]:
    """Find and load the latest PARSE cache, optionally filtered by source.

    Args:
        village_name: Village identifier (supports both 'jintian' and '金田村').
        source: If provided, only match caches with this source tag in filename
                (e.g. "db" matches jintian_db_*.json).
    """
    if not PARSE_CACHE_DIR.exists():
        return None

    # Search all name aliases
    all_candidates = []
    for vname in _resolve_village_names(village_name):
        if source and source != "auto":
            pattern = f"{vname}_{source}_*.json"
        else:
            pattern = f"{vname}_*.json"
        all_candidates.extend(PARSE_CACHE_DIR.glob(pattern))

    candidates = sorted(
        set(all_candidates),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        print(f"  [CACHE] No cache files matching '{pattern}' in {PARSE_CACHE_DIR}", flush=True)
        return None

    print(f"  [CACHE] Found {len(candidates)} cache file(s) matching '{pattern}'", flush=True)
    return load_parse_cache(candidates[0])


def save_parse_cache(result: Dict, village_name: str, source: str = "") -> Path:
    """Save PARSE results to cache file for reuse."""
    PARSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_tag = f"_{source}" if source else ""
    cache_path = PARSE_CACHE_DIR / f"{village_name}{source_tag}_{timestamp}.json"

    with open(str(cache_path), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    file_size_kb = cache_path.stat().st_size / 1024
    print(f"  [CACHE] Saved PARSE cache: {cache_path} ({file_size_kb:.1f} KB)", flush=True)
    return cache_path



# ── Pipeline steps ─────────────────────────────────────────────────


def run_kg_step(
    village_name: str,
    landuse_geojson: Optional[Dict],
    gis_data: dict,
    planning_intent: Any,
) -> Tuple[Dict, bool]:
    """Build KG with Layer 1 caching. Returns (kg_result_dict, cache_hit)."""
    from app.modules.kg.manager import get_kg_manager

    manager = get_kg_manager()
    bundle = None
    try:
        from app.modules.data.catalog import DataCatalog
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle("jintian")
    except Exception:
        pass
    kg, cache_hit = manager.get_or_build_layer1(village_name, bundle=bundle, landuse_geojson=landuse_geojson, gis_data=gis_data)

    # Layer 2: semantic (from intent)
    try:
        zone_areas = kg._compute_zone_areas_from_gis(gis_data)
        kg._build_semantic(intent=planning_intent, zone_areas=zone_areas)
    except Exception as e:
        print(f"  [KG] Semantic build skipped: {e}", flush=True)

    # Layer 3: volatile
    try:
        kg._build_volatile(landuse_geojson=landuse_geojson)
    except Exception as e:
        print(f"  [KG] Volatile build skipped: {e}", flush=True)

    # Phase 4: Add spatial elements (protection zones with within_zone, control lines, etc.)
    # These are needed for get_protected_parcels_detail and other expanded queries
    try:
        kg.add_protection_zones(gis_data)
    except Exception as e:
        print(f"  [KG] Protection zones skipped: {e}", flush=True)
    try:
        kg.add_control_lines(gis_data)
    except Exception as e:
        print(f"  [KG] Control lines skipped: {e}", flush=True)
    try:
        kg.add_planning_elements(gis_data)
    except Exception as e:
        print(f"  [KG] Planning elements skipped: {e}", flush=True)
    try:
        kg.add_natural_features(gis_data)
    except Exception as e:
        print(f"  [KG] Natural features skipped: {e}", flush=True)

    # Extract KG outputs for downstream
    kg_constraints = []
    kg_adjacency_map = {}
    kg_zone_restrictions = {}
    kg_protected_parcels = {}
    kg_parcel_count_by_zone = []

    try:
        kg_constraints = kg.get_constraints() if hasattr(kg, "get_constraints") else []
    except Exception as e:
        print(f"  [KG] WARNING: get_constraints() failed: {e}", flush=True)
    try:
        kg_adjacency_map = kg.get_adjacency_map() if hasattr(kg, "get_adjacency_map") else {}
    except Exception as e:
        print(f"  [KG] WARNING: get_adjacency_map() failed: {e}", flush=True)
    try:
        kg_zone_restrictions = kg.get_zone_restrictions() if hasattr(kg, "get_zone_restrictions") else {}
    except Exception as e:
        print(f"  [KG] WARNING: get_zone_restrictions() failed: {e}", flush=True)
    try:
        kg_protected_parcels = kg.get_protected_parcels() if hasattr(kg, "get_protected_parcels") else {}
    except Exception as e:
        print(f"  [KG] WARNING: get_protected_parcels() failed: {e}", flush=True)

    # Phase 5: expanded KG query results
    kg_protected_parcels_detail = []
    kg_three_zones = []
    kg_three_lines = []
    kg_village_anchors = []
    kg_vne_summary = []
    kg_count_by_planning_zone = []

    try:
        from app.modules.kg.queries import query_kg
        kg_protected_parcels_detail = query_kg(kg, "get_protected_parcels_detail")
    except Exception:
        pass
    try:
        kg_three_zones = query_kg(kg, "get_three_zones")
    except Exception:
        pass
    try:
        kg_three_lines = query_kg(kg, "get_three_lines")
    except Exception:
        pass
    try:
        kg_village_anchors = query_kg(kg, "get_village_anchors")
    except Exception:
        pass
    try:
        kg_vne_summary = query_kg(kg, "count_by_vne")
    except Exception:
        pass
    try:
        kg_count_by_planning_zone = query_kg(kg, "count_by_planning_zone")
    except Exception:
        pass

    kg_result = {
        "triple_count": kg.get_triple_count() if hasattr(kg, "get_triple_count") else 0,
        "constraint_count": len(kg_constraints),
        "adjacency_count": len(kg_adjacency_map),
        "cache_hit": cache_hit,
        "kg_constraints": kg_constraints,
        "kg_adjacency_map": kg_adjacency_map,
        "kg_zone_restrictions": kg_zone_restrictions,
        "kg_protected_parcels": kg_protected_parcels,
        "kg_parcel_count_by_zone": kg_parcel_count_by_zone,
        "kg_turtle": kg.to_turtle() if hasattr(kg, "to_turtle") else "",
        "kg_instance": kg,
        # Phase 5: expanded query results
        "kg_protected_parcels_detail": kg_protected_parcels_detail,
        "kg_three_zones": kg_three_zones,
        "kg_three_lines": kg_three_lines,
        "kg_village_anchors": kg_village_anchors,
        "kg_vne_summary": kg_vne_summary,
        "kg_count_by_planning_zone": kg_count_by_planning_zone,
    }

    print(
        f"  [KG] {kg_result['triple_count']} triples, {kg_result['constraint_count']} constraints, "
        f"{kg_result['adjacency_count']} adjacency entries "
        f"(cache {'HIT' if cache_hit else 'MISS'})",
        flush=True,
    )
    if kg_zone_restrictions:
        print(f"  [KG] Zone restrictions: {len(kg_zone_restrictions)}", flush=True)
    if kg_protected_parcels:
        print(f"  [KG] Protected parcels: {len(kg_protected_parcels)}", flush=True)
    print(
        f"  [KG] Expanded: {len(kg_protected_parcels_detail)} protected_detail, "
        f"{len(kg_three_zones)} three_zones, {len(kg_three_lines)} three_lines, "
        f"{len(kg_village_anchors)} anchors, {len(kg_vne_summary)} VNE classes",
        flush=True,
    )
    return kg_result, cache_hit


def compute_total_area_ha(landuse_geojson: Dict) -> float:
    """Compute total area in hectares from landuse GeoJSON.

    Uses same logic as build_parcel_index: DLMJ / 10000 (fallback SHAPE_Area / 10000).
    """
    total = 0.0
    for feat in landuse_geojson.get("features", []):
        props = feat.get("properties", {})
        dlmj = float(props.get("DLMJ", 0) or 0)
        shape_area = float(props.get("SHAPE_Area", 0) or 0)
        area_sqm = dlmj if dlmj > 0 else shape_area
        total += area_sqm / 10000.0
    return total


def run_allocate_step(
    landuse_geojson: Dict,
    planning_intent: Any,
    kg_result: Dict,
    constraint_set: List[Dict],
    constraint_adjustments: Optional[List[Dict]] = None,
    facility_anchors: Optional[List[Dict]] = None,
) -> Tuple[Dict, Dict]:
    """Run MIP allocation with density_hints + adjacency_rules.

    Returns (allocated_geojson, mip_trace).
    """
    from app.tools.gis._generation.optimizer.mip_allocator import MIPZoneAllocator

    total_area_ha = compute_total_area_ha(landuse_geojson)

    # Reconstruct typed intent from dict if needed
    intent = planning_intent
    if isinstance(planning_intent, dict):
        intent = _reconstruct_intent(planning_intent)

    zone_targets = list(intent.zone_targets) if hasattr(intent, 'zone_targets') and intent.zone_targets else []
    target_map = {zt.land_use: round(zt.area_ratio * total_area_ha, 2) for zt in zone_targets if zt.land_use}

    density_hints = {zt.land_use: zt.density for zt in zone_targets if zt.land_use and zt.density}
    adjacency_rules = {}
    vne_codes = {}
    for zt in zone_targets:
        if zt.land_use and zt.adjacency_rules:
            adjacency_rules[zt.land_use] = {
                "prefer": list(zt.adjacency_rules.prefer) if zt.adjacency_rules.prefer else [],
                "avoid": list(zt.adjacency_rules.avoid) if zt.adjacency_rules.avoid else [],
            }
        if zt.land_use and zt.vne_code:
            vne_codes[zt.land_use] = zt.vne_code

    # Apply constraint adjustments from validate feedback
    if constraint_adjustments:
        for adj in constraint_adjustments:
            zone = adj.get("zone", "")
            delta = adj.get("delta_ha", 0)
            if zone in target_map and delta:
                target_map[zone] = round(target_map[zone] + delta, 2)
                print(f"  [ALLOC] Adjusted {zone} by {delta:+.1f} ha", flush=True)

    # Convert constraint_set to MIP-compatible constraints
    from app.tools.gis.allocate import _spatial_constraint_to_mip
    mip_parse_constraints = []
    if constraint_set:
        for c in constraint_set:
            c_obj = _reconstruct_constraint(c) if isinstance(c, dict) else c
            mip_c = _spatial_constraint_to_mip(c_obj)
            if mip_c:
                mip_parse_constraints.append(mip_c)

    # Merge KG constraints + PARSE area constraints
    all_constraints = list(kg_result.get("kg_constraints") or [])
    if mip_parse_constraints:
        all_constraints.extend(mip_parse_constraints)

    # Inject boundary into landuse for village_center computation
    landuse_with_boundary = dict(landuse_geojson)
    # boundary not available here directly; MIP will fallback to parcel centroids

    allocator = MIPZoneAllocator()
    allocated_geojson, mip_trace = allocator.solve(
        landuse_geojson=landuse_geojson,
        targets=target_map,
        constraints=all_constraints or None,
        zone_targets=zone_targets,
        parse_constraints=constraint_set or None,
        density_hints=density_hints or None,
        adjacency_rules=adjacency_rules or None,
        facility_anchors=facility_anchors,
        protected_parcels_detail=kg_result.get("kg_protected_parcels_detail"),
        three_line_targets=kg_result.get("kg_three_lines"),
        vne_summary=kg_result.get("kg_vne_summary"),
    )

    print(
        f"  [ALLOC] {mip_trace.get('changed_pct', 0):.1f}% parcels changed, "
        f"status={mip_trace.get('solver_status', '?')}, "
        f"objective={mip_trace.get('objective_value', 0):.2f}, "
        f"vars={mip_trace.get('binary_variable_count', 0)}, "
        f"constraints={len(all_constraints)}",
        flush=True,
    )
    # Zone targets vs actuals summary
    zone_targets = mip_trace.get("zone_targets", {})
    zone_actuals = mip_trace.get("zone_actual", {})
    if zone_targets:
        print("  [ALLOC] Zone targets vs actuals:", flush=True)
        for z in sorted(zone_targets.keys()):
            t = zone_targets.get(z, 0)
            a = zone_actuals.get(z, 0)
            dev = mip_trace.get("zone_deviations", {}).get(z, 0)
            print(f"    {z}: target={t:.1f}ha, actual={a:.1f}ha, dev={dev:+.1f}ha", flush=True)
    # Density hints / adjacency rules applied
    meta = mip_trace.get("metadata", {}) or {}
    if meta.get("density_hints_applied"):
        print(f"  [ALLOC] Density hints: {meta['density_hints_applied']}", flush=True)
    if meta.get("adjacency_rules_applied"):
        print(f"  [ALLOC] Adjacency rules: {len(meta['adjacency_rules_applied'])} zones", flush=True)
    return allocated_geojson, mip_trace


# ── Intent / constraint reconstruction from cached dicts ───────────


def _reconstruct_intent(intent_dict: Dict) -> Any:
    """Reconstruct a SpatialPlanningIntent from a cached dict.

    Handles computed fields by stripping them before construction.
    """
    try:
        from app.agent.gis.parse.state import SpatialPlanningIntent, ZoneTarget
        # ZoneTarget has a computed_field (vne_category) that can't be set from dict
        if "zone_targets" in intent_dict:
            for zt in intent_dict["zone_targets"]:
                zt.pop("vne_category", None)
        return SpatialPlanningIntent(**intent_dict)
    except Exception as e:
        print(f"  [RECONSTRUCT] WARNING: intent reconstruction failed: {e}", flush=True)
        return intent_dict


def _reconstruct_constraint(c_dict: Dict) -> Any:
    """Reconstruct a SpatialConstraint from a cached dict."""
    try:
        from app.agent.gis.parse.state import SpatialConstraint
        return SpatialConstraint(**c_dict)
    except Exception as e:
        print(f"  [RECONSTRUCT] WARNING: constraint reconstruction failed: {e}", flush=True)
        return c_dict


# ── Generate step ──────────────────────────────────────────────────


def run_generate_step(
    planning_intent: Any,
    allocated_geojson: Dict,
    gis_data: dict,
    village_name: str,
    operation_sequence: List[Dict],
    kg_session_ref: str = "",
    kg_three_lines: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Generate 6 layout layers directly (bypass @tool decorator)."""
    from app.tools.gis.generate import (
        _apply_operations,
        _generate_function_zones,
        _make_planning_zone_layer,
        _generate_facilities,
        _generate_axes,
        _generate_space_control_zone,
        _generate_land_use_zone,
    )

    intent = _reconstruct_intent(planning_intent) if isinstance(planning_intent, dict) else planning_intent

    # Step 2: Apply PARSE operations to allocated_geojson
    if operation_sequence and allocated_geojson:
        allocated_geojson = _apply_operations(allocated_geojson, operation_sequence)

    layers: List[Dict] = []
    fz = _generate_function_zones(intent, gis_data)
    if fz:
        layers.append(fz)
    pz = _make_planning_zone_layer(allocated_geojson, gis_data)
    if pz:
        layers.append(pz)
    fp = _generate_facilities(intent, gis_data, kg_session_ref=kg_session_ref)
    if fp:
        layers.append(fp)
    ax = _generate_axes(intent, gis_data)
    if ax:
        layers.append(ax)
    sc = _generate_space_control_zone(gis_data, allocated_geojson, intent,
                                      kg_three_lines=kg_three_lines)
    if sc:
        layers.append(sc)
    lu = _generate_land_use_zone(allocated_geojson, gis_data)
    if lu:
        layers.append(lu)

    print(f"  [GEN] {len(layers)} layers: {[l.get('layerType') for l in layers]}", flush=True)
    return layers


# ── Validate step ──────────────────────────────────────────────────


def run_validate_step(layers: List[Dict], kg_constraints: List[Dict],
                      kg_protected_parcels_detail: Optional[List[Dict]] = None,
                      kg_vne_summary: Optional[List[Dict]] = None) -> Tuple[Any, List[Dict]]:
    """Validate layout directly (bypass @tool decorator).

    Returns (validation_report, adjustments).
    """
    from app.tools.gis._validation.layout_validator import LayoutValidator

    validator = LayoutValidator()
    report = validator.validate(
        layers,
        constraints=kg_constraints or None,
        protected_parcels_detail=kg_protected_parcels_detail,
        kg_vne_summary=kg_vne_summary,
    )

    adjustments = getattr(report, "adjustments", None) or []
    status = getattr(report, "status", "fail")
    checks = getattr(report, "checks", [])
    passed_count = sum(1 for c in checks if getattr(c, "passed", False))

    print(
        f"  [VALID] status={status}, {passed_count}/{len(checks)} checks passed, "
        f"{len(adjustments)} adjustments",
        flush=True,
    )
    return report, adjustments


# ── Export step ────────────────────────────────────────────────────


def run_export_step(layers: List[Dict], gis_data: dict, village_name: str, export_dir: Path) -> Dict:
    """Export all layers as GeoJSON files."""
    from app.tools.gis._generation.pipeline import _run_export_step

    export_dir.mkdir(parents=True, exist_ok=True)
    result = _run_export_step(
        layers=layers,
        gis_data=gis_data,
        output_dir=export_dir,
        village_name=village_name,
    )
    print(f"  [EXPORT] {result.get('exported_files', 0)} files -> {export_dir}", flush=True)
    return result


# ── Render step ────────────────────────────────────────────────────


def run_render_step(layers: List[Dict], gis_data: dict, village_name: str, render_dir: Path) -> Dict:
    """Render map layers as PNG using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from shapely.geometry import shape

    render_dir.mkdir(parents=True, exist_ok=True)

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    from app.modules.schema import PLANNING_ZONE_COLORS

    boundary = gis_data.get("boundary_geojson")
    allocated = None
    for lyr in layers:
        if lyr.get("layerType") == "planning_zone":
            allocated = lyr.get("data")

    results = {"png_files": [], "render_dir": str(render_dir)}

    # 1. Planning zone map with change highlighting
    pz_path = render_dir / "planning_zone.png"
    try:
        _render_planning_zone(layers, boundary, pz_path, PLANNING_ZONE_COLORS, shape)
        results["png_files"].append(str(pz_path))
        print(f"  [RENDER] planning_zone.png", flush=True)
    except Exception as e:
        print(f"  [RENDER] planning_zone failed: {e}", flush=True)

    # 2. Comparison: current vs planned
    comp_path = render_dir / "comparison.png"
    try:
        _render_comparison(gis_data, allocated, comp_path, PLANNING_ZONE_COLORS, shape)
        results["png_files"].append(str(comp_path))
        print(f"  [RENDER] comparison.png", flush=True)
    except Exception as e:
        print(f"  [RENDER] comparison failed: {e}", flush=True)

    # 3. Composite: all layers stacked
    composite_path = render_dir / "composite.png"
    try:
        _render_composite(layers, boundary, composite_path, PLANNING_ZONE_COLORS, shape)
        results["png_files"].append(str(composite_path))
        print(f"  [RENDER] composite.png", flush=True)
    except Exception as e:
        print(f"  [RENDER] composite failed: {e}", flush=True)

    plt.close("all")
    return results


def _draw_geojson_layer(ax, geojson, facecolor="#AAAAAA", edgecolor="#333333",
                        linewidth=0.5, alpha=0.5, shape=None):
    """Draw a GeoJSON FeatureCollection on a matplotlib Axes."""
    if shape is None:
        from shapely.geometry import shape
    for feat in geojson.get("features", []):
        try:
            geom = shape(feat.get("geometry", {}))
            if geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                xs, ys = geom.exterior.xy
                ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor,
                        linewidth=linewidth, alpha=alpha)
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    xs, ys = poly.exterior.xy
                    ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor,
                            linewidth=linewidth, alpha=alpha)
            elif geom.geom_type in ("LineString", "MultiLineString"):
                lines = [geom] if geom.geom_type == "LineString" else geom.geoms
                for line in lines:
                    xs, ys = line.xy
                    ax.plot(xs, ys, color=edgecolor, linewidth=linewidth * 2, alpha=alpha)
            elif geom.geom_type == "Point":
                ax.plot(geom.x, geom.y, "o", color=facecolor, markersize=4, alpha=alpha)
        except Exception as _draw_err:
            # Log first few geometry errors, then suppress to avoid flooding
            if not hasattr(_draw_geojson_layer, '_err_count'):
                _draw_geojson_layer._err_count = 0
            _draw_geojson_layer._err_count += 1
            if _draw_geojson_layer._err_count <= 3:
                print(f"  [RENDER] Geometry draw error: {_draw_err}", flush=True)
            continue


def _render_planning_zone(layers, boundary, out_path, colors, shape):
    """Render planning_zone layer with 4-zone color coding."""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    pz_data = None
    for lyr in layers:
        if lyr.get("layerType") == "planning_zone":
            pz_data = lyr.get("data")
            break
    if not pz_data:
        return

    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    ax.set_aspect("equal")
    ax.set_title("Planning Zone Allocation", fontsize=14)

    if boundary and boundary.get("features"):
        _draw_geojson_layer(ax, boundary, edgecolor="#333333", facecolor="none",
                            linewidth=1.5, shape=shape)

    legend_patches = []
    for zone_name, color in colors.items():
        zone_features = {
            "type": "FeatureCollection",
            "features": [
                f for f in pz_data.get("features", [])
                if f.get("properties", {}).get("zone_type") == zone_name
            ],
        }
        if zone_features["features"]:
            _draw_geojson_layer(ax, zone_features, facecolor=color, alpha=0.7, shape=shape)
            legend_patches.append(mpatches.Patch(color=color, label=zone_name))

    if legend_patches:
        ax.legend(handles=legend_patches, loc="lower right", fontsize=8)
    ax.autoscale()
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_comparison(gis_data, allocated, out_path, colors, shape):
    """Render side-by-side: current landuse vs allocated planning zones."""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    current = gis_data.get("landuse_current_geojson")
    if not current or not allocated:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(24, 10))
    for ax, title in [(ax1, "Current Landuse"), (ax2, "Allocated Planning Zones")]:
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=12)

    _draw_geojson_layer(ax1, current, facecolor="#CCCCCC", alpha=0.5, shape=shape)

    legend_patches = []
    for zone_name, color in colors.items():
        zone_features = {
            "type": "FeatureCollection",
            "features": [
                f for f in allocated.get("features", [])
                if f.get("properties", {}).get("zone_type") == zone_name
            ],
        }
        if zone_features["features"]:
            _draw_geojson_layer(ax2, zone_features, facecolor=color, alpha=0.7, shape=shape)
            legend_patches.append(mpatches.Patch(color=color, label=zone_name))

    if legend_patches:
        ax2.legend(handles=legend_patches, loc="lower right", fontsize=7)
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_composite(layers, boundary, out_path, colors, shape):
    """Render all layers stacked."""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    ax.set_aspect("equal")
    ax.set_title("Composite Layout", fontsize=14)

    if boundary and boundary.get("features"):
        _draw_geojson_layer(ax, boundary, edgecolor="#333333", facecolor="none",
                            linewidth=1.5, shape=shape)

    legend_patches = []
    for lyr in layers:
        layer_type = lyr.get("layerType", "unknown")
        geojson = lyr.get("data")
        if not geojson or not geojson.get("features"):
            continue

        if layer_type == "planning_zone":
            for zone_name, color in colors.items():
                zone_features = {
                    "type": "FeatureCollection",
                    "features": [
                        f for f in geojson["features"]
                        if f.get("properties", {}).get("zone_type") == zone_name
                    ],
                }
                if zone_features["features"]:
                    _draw_geojson_layer(ax, zone_features, facecolor=color, alpha=0.5, shape=shape)
                    legend_patches.append(mpatches.Patch(color=color, label=zone_name))
        elif layer_type == "infrastructure":
            _draw_geojson_layer(ax, geojson, edgecolor="#FF0000", facecolor="none",
                                linewidth=2, alpha=0.8, shape=shape)
            legend_patches.append(mpatches.Patch(color="#FF0000", label="Axis"))
        elif layer_type == "facility_point":
            _draw_geojson_layer(ax, geojson, facecolor="#0000FF", edgecolor="#0000FF",
                                alpha=0.9, shape=shape)
            legend_patches.append(mpatches.Patch(color="#0000FF", label="Facility"))

    if legend_patches:
        ax.legend(handles=legend_patches, loc="lower right", fontsize=7)
    ax.autoscale()
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Report generation ──────────────────────────────────────────────


def generate_layout_report(
    village_name: str,
    kg_result: Dict,
    mip_trace: Dict,
    validation_report: Any,
    validation_round: int,
    export_result: Dict,
    render_result: Dict,
    timing: Dict,
    output_dir: Path,
) -> Path:
    """Generate Markdown report for layout pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = output_dir / f"{village_name}_layout_{date_str}.md"

    status = getattr(validation_report, "status", "fail")
    checks = getattr(validation_report, "checks", [])

    lines = []
    lines.append(f"# {village_name} LAYOUT Pipeline Report")
    lines.append("")
    lines.append(f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> Validation: {'PASS' if status == 'pass' else 'FAIL'} (round {validation_round})")
    lines.append(f"> Total time: {timing.get('total_seconds', 0):.1f}s")
    lines.append("")

    # Section 1: KG
    lines.append("---")
    lines.append("")
    lines.append("## 1. Knowledge Graph")
    lines.append("")
    cache_status = "HIT" if kg_result.get("cache_hit") else "MISS"
    lines.append(f"- Triple count: {kg_result.get('triple_count', 0)}")
    lines.append(f"- Constraint count: {kg_result.get('constraint_count', 0)}")
    lines.append(f"- Adjacency entries: {kg_result.get('adjacency_count', 0)}")
    lines.append(f"- Layer 1 cache: {cache_status}")
    lines.append("")

    # Section 2: MIP Allocation
    lines.append("---")
    lines.append("")
    lines.append("## 2. MIP Allocation")
    lines.append("")
    metadata = mip_trace.get("metadata", {}) or {}
    lines.append(f"- Solver status: {mip_trace.get('solver_status', '?')}")
    lines.append(f"- Objective value: {mip_trace.get('objective_value', 0):.2f}")
    lines.append(f"- Binary variables: {mip_trace.get('binary_variable_count', 0)}")
    lines.append(f"- Changed parcels: {mip_trace.get('changed_pct', 0):.1f}%")
    lines.append(f"- PARSE constraints applied: {metadata.get('parse_constraint_count', 0)}")
    lines.append("")

    density_hints = metadata.get("density_hints_applied", {})
    adjacency_rules = metadata.get("adjacency_rules_applied", {})
    if density_hints:
        lines.append(f"- Density hints: {density_hints}")
    if adjacency_rules:
        lines.append(f"- Adjacency rules: {adjacency_rules}")
    lines.append("")

    # Zone targets vs actual
    lines.append("### Zone Targets vs Actual")
    lines.append("")
    lines.append("| Zone | Target (ha) | Actual (ha) | Deviation (ha) |")
    lines.append("|------|-------------|-------------|----------------|")
    targets = mip_trace.get("zone_targets", {})
    actuals = mip_trace.get("zone_actual", {})
    devs = mip_trace.get("zone_deviations", {})
    for zone in sorted(set(list(targets.keys()) + list(actuals.keys()))):
        t = targets.get(zone, 0)
        a = actuals.get(zone, 0)
        d = devs.get(zone, 0)
        lines.append(f"| {zone} | {t:.1f} | {a:.1f} | {d:+.1f} |")
    lines.append("")

    # Section 3: Validation
    lines.append("---")
    lines.append("")
    lines.append("## 3. Validation")
    lines.append("")
    lines.append(f"- Status: {status}")
    lines.append(f"- Rounds: {validation_round}")
    lines.append("")
    lines.append("| Check | Passed | Violations |")
    lines.append("|-------|--------|------------|")
    for c in checks:
        name = getattr(c, "check_name", "?")
        passed = getattr(c, "passed", False)
        n_viol = len(getattr(c, "violations", []))
        lines.append(f"| {name} | {'yes' if passed else 'no'} | {n_viol} |")
    lines.append("")

    adjustments = getattr(validation_report, "adjustments", None) or []
    if adjustments:
        lines.append("### Adjustments")
        lines.append("")
        lines.append("| Zone | Action | Delta (ha) | Reason |")
        lines.append("|------|--------|------------|--------|")
        for a in adjustments:
            lines.append(
                f"| {a.zone} | {a.action} | {a.delta_ha:+.1f} | {a.reason} |"
            )
        lines.append("")

    # Section 4: Export
    lines.append("---")
    lines.append("")
    lines.append("## 4. Export")
    lines.append("")
    files = export_result.get("files", [])
    lines.append(f"- Exported files: {len(files)}")
    lines.append(f"- Output dir: {export_result.get('output_dir', '?')}")
    if files:
        lines.append("")
        for fp in files[:20]:
            lines.append(f"  - `{Path(fp).name}`")
        if len(files) > 20:
            lines.append(f"  - ... and {len(files) - 20} more")
    lines.append("")

    # Section 5: Render
    lines.append("---")
    lines.append("")
    lines.append("## 5. Render")
    lines.append("")
    pngs = render_result.get("png_files", [])
    lines.append(f"- Render dir: {render_result.get('render_dir', '?')}")
    for png in pngs:
        lines.append(f"- `{Path(png).name}`")
    lines.append("")

    # Section 6: Timing
    lines.append("---")
    lines.append("")
    lines.append("## 6. Timing")
    lines.append("")
    lines.append("| Step | Time (s) |")
    lines.append("|------|----------|")
    for step, t in sorted(timing.items()):
        if step == "total_seconds":
            continue
        if isinstance(t, (int, float)):
            lines.append(f"| {step} | {t:.1f} |")
    lines.append(f"| **total** | **{timing.get('total_seconds', 0):.1f}** |")
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ── MIP result export ──────────────────────────────────────────────


def export_mip_results(mip_trace: Dict, output_dir: Path, village_name: str) -> Path:
    """Export MIP allocation results as structured JSON' for downstream analysis."""
    result = {
        "village_name": village_name,
        "timestamp": datetime.now().isoformat(),
        "solver_status": mip_trace.get("solver_status"),
        "objective_value": mip_trace.get("objective_value"),
        "binary_variable_count": mip_trace.get("binary_variable_count"),
        "changed_parcels_pct": mip_trace.get("changed_pct"),
        "zone_targets_ha": mip_trace.get("zone_targets", {}),
        "zone_actual_ha": mip_trace.get("zone_actual", {}),
        "zone_deviations_ha": mip_trace.get("zone_deviations", {}),
        "kg_slack_values": mip_trace.get("kg_slack_values", {}),
        "metadata": mip_trace.get("metadata", {}),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    mip_path = output_dir / "mip_result.json"
    mip_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    file_size_kb = mip_path.stat().st_size / 1024
    print(
        f"  [MIP] Exported: {mip_path} ({file_size_kb:.1f} KB, "
        f"status={mip_trace.get('solver_status', '?')}, "
        f"zones={len(mip_trace.get('zone_targets', {}))})",
        flush=True,
    )
    return mip_path


# ── Structured trace files for optimization analysis ────────────────


def _save_trace_files(
    out_base: Path,
    village_name: str,
    parse_source: str,
    kg_result: Dict,
    allocated_geojson: Dict,
    mip_trace: Dict,
    validation_history: List[Dict],
    constraint_adjustments: List[Dict],
    layers: List[Dict],
    timing: Dict,
    parse_result: Dict,
) -> None:
    """Save structured JSON trace files for post-hoc optimization analysis.

    Files produced:
      kg_output.json         — KG constraints, adjacency, restrictions, protected parcels, turtle
      allocation_result.json — Raw allocated GeoJSON + full mip_trace + adjustments history
      validation_detail.json — Per-round checks, violations, adjustments
      pipeline_run.json      — Single-file index: timing, source, config, all output paths
    """
    ts = datetime.now().isoformat()

    # 1. kg_output.json — full KG spatial reasoning output
    try:
        kg_data = {
            "village_name": village_name,
            "timestamp": ts,
            "triple_count": kg_result.get("triple_count", 0),
            "constraint_count": kg_result.get("constraint_count", 0),
            "adjacency_count": kg_result.get("adjacency_count", 0),
            "cache_hit": kg_result.get("cache_hit", False),
            "kg_constraints": kg_result.get("kg_constraints", []),
            "kg_adjacency_map": kg_result.get("kg_adjacency_map", {}),
            "kg_zone_restrictions": kg_result.get("kg_zone_restrictions", {}),
            "kg_protected_parcels": kg_result.get("kg_protected_parcels", {}),
            "kg_turtle": kg_result.get("kg_turtle", ""),
            # Phase 5: expanded KG query results
            "kg_protected_parcels_detail": kg_result.get("kg_protected_parcels_detail", []),
            "kg_three_zones": kg_result.get("kg_three_zones", []),
            "kg_three_lines": kg_result.get("kg_three_lines", []),
            "kg_village_anchors": kg_result.get("kg_village_anchors", []),
            "kg_vne_summary": kg_result.get("kg_vne_summary", []),
        }
        kg_path = out_base / "kg_output.json"
        kg_path.write_text(
            json.dumps(kg_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [TRACE] kg_output.json ({kg_path.stat().st_size / 1024:.1f} KB)", flush=True)
    except Exception as e:
        print(f"  [TRACE] WARNING: Failed to save kg_output.json: {e}", flush=True)

    # 2. allocation_result.json — raw allocation + full MIP trace + adjustments
    try:
        alloc_data = {
            "village_name": village_name,
            "timestamp": ts,
            "allocated_geojson": allocated_geojson,
            "mip_trace_full": mip_trace,
            "constraint_adjustments_final": constraint_adjustments,
            "validation_rounds": len(validation_history),
        }
        alloc_path = out_base / "allocation_result.json"
        alloc_path.write_text(
            json.dumps(alloc_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [TRACE] allocation_result.json ({alloc_path.stat().st_size / 1024:.1f} KB)", flush=True)
    except Exception as e:
        print(f"  [TRACE] WARNING: Failed to save allocation_result.json: {e}", flush=True)

    # 3. validation_detail.json — per-round checks + violations + adjustments
    try:
        val_data = {
            "village_name": village_name,
            "timestamp": ts,
            "total_rounds": len(validation_history),
            "final_status": validation_history[-1].get("status", "?") if validation_history else "none",
            "rounds": validation_history,
        }
        val_path = out_base / "validation_detail.json"
        val_path.write_text(
            json.dumps(val_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [TRACE] validation_detail.json ({val_path.stat().st_size / 1024:.1f} KB)", flush=True)
    except Exception as e:
        print(f"  [TRACE] WARNING: Failed to save validation_detail.json: {e}", flush=True)

    # 4. pipeline_run.json — single-file index of all outputs
    try:
        # Collect layer feature counts
        layer_summary = []
        for lyr in layers:
            lt = lyr.get("layerType", "?")
            feat_count = len(lyr.get("data", {}).get("features", []))
            layer_summary.append({"layerType": lt, "feature_count": feat_count})

        # Collect output file paths
        geojson_dir = out_base / "geojson"
        render_dir = out_base / "render"
        output_files = {
            "report": str(out_base / "report.md"),
            "mip_result": str(out_base / "mip_result.json"),
            "kg_output": str(out_base / "kg_output.json"),
            "allocation_result": str(out_base / "allocation_result.json"),
            "validation_detail": str(out_base / "validation_detail.json"),
            "geojson_dir": str(geojson_dir),
            "render_dir": str(render_dir),
        }

        run_data = {
            "village_name": village_name,
            "timestamp": ts,
            "parse_source": parse_source,
            "timing": timing,
            "layer_summary": layer_summary,
            "mip_summary": {
                "solver_status": mip_trace.get("solver_status", "?"),
                "objective_value": mip_trace.get("objective_value", 0),
                "changed_pct": mip_trace.get("changed_pct", 0),
                "zone_count": len(mip_trace.get("zone_targets", {})),
            },
            "validation_summary": {
                "total_rounds": len(validation_history),
                "final_status": validation_history[-1].get("status", "?") if validation_history else "none",
            },
            "parse_cache_info": {
                "source": parse_result.get("source", "unknown"),
                "timestamp": parse_result.get("timestamp", ""),
                "zone_targets_count": len(
                    parse_result.get("planning_intent", {}).get("zone_targets", [])
                ),
                "operations_count": len(parse_result.get("operation_sequence", [])),
                "constraints_count": len(parse_result.get("constraint_set", [])),
            },
            "output_files": output_files,
        }
        run_path = out_base / "pipeline_run.json"
        run_path.write_text(
            json.dumps(run_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  [TRACE] pipeline_run.json", flush=True)
    except Exception as e:
        print(f"  [TRACE] WARNING: Failed to save pipeline_run.json: {e}", flush=True)


# ── Comparison report ──────────────────────────────────────────────


def generate_comparison_report(
    result_a: Dict, label_a: str,
    result_b: Dict, label_b: str,
    output_dir: Path,
) -> Path:
    """Generate comparison report between two layout pipeline runs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"comparison_{label_a}_vs_{label_b}.md"

    mip_a = result_a.get("mip_trace", {})
    mip_b = result_b.get("mip_trace", {})

    lines = []
    lines.append(f"# Comparison: {label_a} vs {label_b}")
    lines.append("")
    lines.append(f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Solver status
    lines.append("## Solver Status")
    lines.append("")
    lines.append(f"| | {label_a} | {label_b} |")
    lines.append(f"|------|------|------|")
    lines.append(f"| Status | {mip_a.get('solver_status', '?')} | {mip_b.get('solver_status', '?')} |")
    lines.append(f"| Objective | {mip_a.get('objective_value', 0):.2f} | {mip_b.get('objective_value', 0):.2f} |")
    lines.append(f"| Changed % | {mip_a.get('changed_pct', 0):.1f}% | {mip_b.get('changed_pct', 0):.1f}% |")
    lines.append("")

    # Zone deviations comparison
    all_zones = sorted(set(
        list(mip_a.get("zone_targets", {}).keys())
        + list(mip_b.get("zone_targets", {}).keys())
    ))
    lines.append("## Zone Targets Comparison (ha)")
    lines.append("")
    lines.append(f"| Zone | {label_a} Target | {label_a} Actual | {label_b} Target | {label_b} Actual | Delta Actual |")
    lines.append(f"|------|-------------|-------------|-------------|-------------|-------------|")
    for z in all_zones:
        t_a = mip_a.get("zone_targets", {}).get(z, 0)
        a_a = mip_a.get("zone_actual", {}).get(z, 0)
        t_b = mip_b.get("zone_targets", {}).get(z, 0)
        a_b = mip_b.get("zone_actual", {}).get(z, 0)
        delta = a_b - a_a
        lines.append(f"| {z} | {t_a:.1f} | {a_a:.1f} | {t_b:.1f} | {a_b:.1f} | {delta:+.1f} |")
    lines.append("")

    # Metadata comparison (density_hints, adjacency_rules)
    meta_a = mip_a.get("metadata", {}) or {}
    meta_b = mip_b.get("metadata", {}) or {}
    lines.append("## MIP Metadata Comparison")
    lines.append("")
    for key in ["density_hints_applied", "adjacency_rules_applied", "parse_constraint_count"]:
        val_a = meta_a.get(key, "N/A")
        val_b = meta_b.get(key, "N/A")
        match = "same" if val_a == val_b else "**DIFFER**"
        lines.append(f"- {key}: {label_a}={val_a}, {label_b}={val_b} ({match})")
    lines.append("")

    # Timing comparison
    timing_a = result_a.get("timing", {})
    timing_b = result_b.get("timing", {})
    lines.append("## Timing Comparison")
    lines.append("")
    lines.append(f"| | {label_a} | {label_b} |")
    lines.append(f"|------|------|------|")
    lines.append(f"| Total | {timing_a.get('total_seconds', 0):.1f}s | {timing_b.get('total_seconds', 0):.1f}s |")
    for step in ["kg", "allocate"]:
        lines.append(f"| {step} | {timing_a.get(step, 0):.1f}s | {timing_b.get(step, 0):.1f}s |")
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ── Main pipeline ──────────────────────────────────────────────────


async def run_pipeline(
    parse_cache_path: Optional[Path] = None,
    source: str = "auto",
    village_name: str = "jintian",
    output_dir: Optional[Path] = None,
) -> Dict:
    """Run the full LAYOUT pipeline from cached PARSE output.

    This pipeline is INDEPENDENT from the PARSE pipeline. It only reads
    PARSE results from the cache directory — it never runs PARSE inline.
    Run run_parse_pipeline.py first to populate the cache.

    Args:
        parse_cache_path: Direct path to a PARSE cache JSON file (highest priority).
        source: Filter cache lookup by source tag — "auto" (any), "db",
                "mineru", "json", "text".
        village_name: Village identifier.
        output_dir: Override output directory.
    """
    total_start = time.time()
    timing: Dict[str, Any] = {}

    out_base = output_dir or (OUTPUT_DIR / f"{village_name}_{datetime.now().strftime('%Y-%m-%d')}")
    out_base.mkdir(parents=True, exist_ok=True)

    # Step 0: Load GIS data
    with StepTimer("Load GIS data"):
        t0 = time.time()
        gis_data, annotations, roads = load_gis_data()
        timing["load_gis"] = time.time() - t0

    landuse_geojson = gis_data.get("landuse_current_geojson")

    # Step 1: Get PARSE results (cache only — no inline PARSE)
    with StepTimer("Get PARSE results"):
        t0 = time.time()
        parse_result = None
        if parse_cache_path:
            parse_result = load_parse_cache(parse_cache_path)
        if not parse_result:
            parse_result = load_latest_parse_cache(village_name, source=source)

        if not parse_result:
            print(
                "  [ERROR] No PARSE cache found. Run run_parse_pipeline.py first "
                f"(source={source}).",
                flush=True,
            )
            return {"error": "no_parse_result"}

        parse_source = parse_result.get("source", "unknown")
        print(f"  [PARSE] Loaded from cache (source={parse_source})", flush=True)

        planning_intent = parse_result.get("planning_intent", {})
        operation_sequence = parse_result.get("operation_sequence", [])
        constraint_set = parse_result.get("constraint_set", [])

        # Extract facility_anchors from spatial_context (annotation-derived, optional)
        spatial_context_data = parse_result.get("spatial_context", {}) or {}
        facility_anchors = spatial_context_data.get("facility_anchors", []) if isinstance(spatial_context_data, dict) else []

        timing["parse"] = time.time() - t0

    # Step 2: Build KG
    with StepTimer("Build Knowledge Graph"):
        t0 = time.time()
        kg_result, cache_hit = run_kg_step(
            village_name, landuse_geojson, gis_data, planning_intent
        )
        timing["kg"] = time.time() - t0

    # Step 3: Allocate (MIP)
    with StepTimer("MIP Allocation"):
        t0 = time.time()
        allocated_geojson, mip_trace = run_allocate_step(
            landuse_geojson, planning_intent, kg_result, constraint_set,
            facility_anchors=facility_anchors,
        )
        timing["allocate"] = time.time() - t0

    # Step 4: Generate layers + validate (retry loop)
    constraint_adjustments: List[Dict] = []
    validation_report = None
    validation_round = 0
    layers: List[Dict] = []
    validation_history: List[Dict] = []  # Per-round detail for optimization analysis

    for round_num in range(1, MAX_VALIDATION_ROUNDS + 1):
        with StepTimer(f"Generate + Validate (round {round_num})"):
            t0 = time.time()
            layers = run_generate_step(
                planning_intent, allocated_geojson, gis_data, village_name, operation_sequence,
                kg_session_ref=kg_result.get("kg_session_ref", ""),
                kg_three_lines=kg_result.get("kg_three_lines"),
            )
            validation_report, adjustments = run_validate_step(
                layers, kg_result.get("kg_constraints", []),
                kg_protected_parcels_detail=kg_result.get("kg_protected_parcels_detail"),
                kg_vne_summary=kg_result.get("kg_vne_summary"),
            )
            validation_round = round_num
            timing[f"generate_validate_r{round_num}"] = time.time() - t0

            # Capture per-round validation detail
            checks = getattr(validation_report, "checks", [])
            round_detail = {
                "round": round_num,
                "status": getattr(validation_report, "status", "fail"),
                "checks_total": len(checks),
                "checks_passed": sum(1 for c in checks if getattr(c, "passed", False)),
                "checks": [
                    {
                        "name": getattr(c, "check_name", getattr(c, "name", "")),
                        "passed": getattr(c, "passed", False),
                        "violation_count": getattr(c, "violation_count", 0),
                        "message": getattr(c, "message", ""),
                    }
                    for c in checks
                ],
                "adjustments": [],
            }

            status = getattr(validation_report, "status", "fail")
            if status == "pass":
                print(f"  [VALID] Passed at round {round_num}", flush=True)
                validation_history.append(round_detail)
                break

            if round_num < MAX_VALIDATION_ROUNDS and adjustments:
                constraint_adjustments = [
                    {
                        "zone": a.zone,
                        "action": a.action,
                        "delta_ha": a.delta_ha,
                        "reason": a.reason,
                        "priority": a.priority,
                    }
                    for a in adjustments
                ]
                round_detail["adjustments"] = constraint_adjustments
                validation_history.append(round_detail)
                print(f"  [VALID] Failed, retrying with {len(adjustments)} adjustments...", flush=True)
                allocated_geojson, mip_trace = run_allocate_step(
                    landuse_geojson, planning_intent, kg_result, constraint_set,
                    constraint_adjustments=constraint_adjustments,
                    facility_anchors=facility_anchors,
                )
            else:
                validation_history.append(round_detail)
                print(f"  [VALID] Max rounds reached, using current result", flush=True)

    # Step 5: Export
    with StepTimer("Export GeoJSON"):
        t0 = time.time()
        export_dir = out_base / "geojson"
        export_result = run_export_step(layers, gis_data, village_name, export_dir)
        timing["export"] = time.time() - t0

    # Step 5b: Export MIP results
    with StepTimer("Export MIP results"):
        mip_export_path = export_mip_results(mip_trace, out_base, village_name)

    # Step 5c: Save structured JSON trace files for optimization analysis
    with StepTimer("Save trace files"):
        _save_trace_files(
            out_base=out_base,
            village_name=village_name,
            parse_source=parse_source,
            kg_result=kg_result,
            allocated_geojson=allocated_geojson,
            mip_trace=mip_trace,
            validation_history=validation_history,
            constraint_adjustments=constraint_adjustments,
            layers=layers,
            timing=timing,
            parse_result=parse_result,
        )

    # Step 6: Render
    with StepTimer("Render PNG"):
        t0 = time.time()
        render_dir = out_base / "render"
        render_result = run_render_step(layers, gis_data, village_name, render_dir)
        timing["render"] = time.time() - t0

    # Step 7: Generate report
    with StepTimer("Generate report"):
        timing["total_seconds"] = time.time() - total_start
        report_path = generate_layout_report(
            village_name=village_name,
            kg_result=kg_result,
            mip_trace=mip_trace,
            validation_report=validation_report,
            validation_round=validation_round,
            export_result=export_result,
            render_result=render_result,
            timing=timing,
            output_dir=out_base,
        )
        print(f"  [REPORT] {report_path}", flush=True)

    print(f"\n{'=' * 60}", flush=True)
    print(f"Total time: {timing['total_seconds']:.1f}s", flush=True)
    print(f"Output: {out_base}", flush=True)
    print(f"{'=' * 60}", flush=True)

    return {
        "report_path": str(report_path),
        "output_dir": str(out_base),
        "mip_trace": mip_trace,
        "validation_round": validation_round,
        "validation_history": validation_history,
        "timing": timing,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run LAYOUT pipeline from cached PARSE output (independent from PARSE pipeline)"
    )
    parser.add_argument(
        "--source", choices=["auto", "db", "mineru", "json", "text"], default="auto",
        help="Filter PARSE cache by source tag (default: auto=any)",
    )
    parser.add_argument("--parse-cache", type=str, help="Direct path to PARSE cache JSON (overrides --source)")
    parser.add_argument("--village", default="jintian", help="Village name")
    parser.add_argument("--output", type=str, help="Output directory")
    parser.add_argument("--compare", action="store_true", help="Run DB vs MinerU comparison")
    args = parser.parse_args()

    if args.compare:
        out_root = Path(args.output) if args.output else (
            OUTPUT_DIR / f"{args.village}_comparison_{datetime.now().strftime('%Y-%m-%d')}"
        )

        async def _compare():
            result_db = await run_pipeline(
                source="db", village_name=args.village, output_dir=out_root / "db",
            )
            result_mineru = await run_pipeline(
                source="mineru", village_name=args.village, output_dir=out_root / "mineru",
            )
            # Guard: skip comparison if either run failed
            if result_db.get("error"):
                print(f"\n[COMPARE] DB run failed: {result_db['error']}", flush=True)
                return
            if result_mineru.get("error"):
                print(f"\n[COMPARE] MinerU run failed: {result_mineru['error']}", flush=True)
                return
            cmp_path = generate_comparison_report(
                result_db, "db", result_mineru, "mineru", out_root,
            )
            print(f"\n[COMPARE] Report: {cmp_path}", flush=True)

        asyncio.run(_compare())
    else:
        asyncio.run(
            run_pipeline(
                parse_cache_path=Path(args.parse_cache) if args.parse_cache else None,
                source=args.source,
                village_name=args.village,
                output_dir=Path(args.output) if args.output else None,
            )
        )
