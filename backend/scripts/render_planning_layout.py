"""Render planning layout layers as matplotlib maps for visual validation.

Generates PNG images:
1. planning_zone — 4-zone allocation (farmland / construction / ecological / agriculture)
2. function_zone — DLBM-reclassified current use zones
3. Comparison overlay — current vs planned with change highlighting
4. Full composite — all layers stacked

Usage:
  cd backend && python scripts/render_planning_layout.py
  cd backend && python scripts/render_planning_layout.py --output test-screenshots
"""

from __future__ import annotations

import json
import os
import sys
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.modules.gis.schema import (
    ZONE_TYPE_COLORS,
    PLANNING_ZONE_COLORS,
    FACILITY_STATUS_COLORS,
)
from app.modules.gis.layout.zone_generator import ZoneGenerator
from app.modules.gis.layout.facility_placer import FacilityPlacer
from app.modules.gis.layout.axis_builder import AxisBuilder
from app.modules.gis.layout.map_renderer import MapRenderer
from app.modules.gis.kg import PlanningKG
from app.modules.gis.schema.intent import (
    UnifiedSpatialIntent, ZoneIntent, Direction, Density,
)
from app.database.engine import get_db_path

# ── Color tables ──────────────────────────────────────────────

PLANNING_ZONE_MPL = {
    "农田保护区": {"fill": "#FFE4B5", "stroke": "#DAA520", "label": "Farmland Reserve"},
    "村庄建设区": {"fill": "#FF6347", "stroke": "#CC4F39", "label": "Village Construction"},
    "生态保护区": {"fill": "#2E8B57", "stroke": "#1B5E20", "label": "Ecological Protection"},
    "一般农业区": {"fill": "#98FB98", "stroke": "#66CD66", "label": "General Agriculture"},
}

FUNCTION_ZONE_MPL = {k: {"fill": v["fill"], "stroke": v["stroke"], "label": k}
                     for k, v in ZONE_TYPE_COLORS.items()}

FACILITY_MPL = {k: {"fill": v["fill"], "stroke": v["stroke"], "label": k}
                for k, v in FACILITY_STATUS_COLORS.items()}

# ── Data loading ──────────────────────────────────────────────

def load_all() -> Tuple[Dict, Optional[Dict], Optional[Dict], Optional[Dict]]:
    """Load DB reports + GIS data from jintian test files."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT session_id FROM dimension_reports WHERE layer=3 "
        "ORDER BY generated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}, None, None, None

    session_id = row["session_id"]
    cur = conn.execute(
        "SELECT dimension_key, summary FROM dimension_reports "
        "WHERE session_id=? AND layer=3", (session_id,)
    )
    rows = cur.fetchall()
    conn.close()

    reports = {}
    for r in rows:
        dk = r["dimension_key"]
        summary_text = r["summary"] or ""
        parsed = json.loads(summary_text) if summary_text else {}
        reports[dk] = {
            "summary": {
                "metrics": parsed.get("metrics", {}),
                "key_points": parsed.get("key_points", []),
                "text_summary": parsed.get("text_summary", ""),
            },
            "content": parsed.get("text_summary", ""),
        }

    from app.core.settings import JINTIAN_GIS_DIR
    data_dir = str(JINTIAN_GIS_DIR)

    boundary = _load_geojson(os.path.join(data_dir, "current", "boundary.geojson"))
    landuse = _load_geojson(os.path.join(data_dir, "current", "landuse.geojson"))
    roads = _load_geojson(os.path.join(data_dir, "current", "road.geojson"))

    return reports, boundary, landuse, roads


def _load_geojson(path: str) -> Optional[Dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Rendering engine ──────────────────────────────────────────

def _setup_matplotlib():
    """Configure matplotlib for CJK + Agg backend."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _draw_polygons(ax, geom, facecolor, edgecolor, alpha=0.5, linewidth=0.5, hatch=None):
    """Draw shapely Polygon/MultiPolygon onto matplotlib axes."""
    from matplotlib.patches import Polygon as MplPolygon

    polys = [geom] if geom.geom_type == "Polygon" else getattr(geom, "geoms", [])
    for poly in polys:
        if poly.is_empty or not hasattr(poly, "exterior"):
            continue
        patch = MplPolygon(
            list(poly.exterior.coords), closed=True,
            facecolor=facecolor, edgecolor=edgecolor,
            alpha=alpha, linewidth=linewidth, hatch=hatch,
        )
        ax.add_patch(patch)


def _draw_linestring(ax, geom, color, linewidth=2, alpha=0.8, linestyle="-"):
    """Draw shapely LineString onto matplotlib axes."""
    if geom.geom_type == "MultiLineString":
        for line in geom.geoms:
            x, y = line.xy
            ax.plot(x, y, color=color, linewidth=linewidth, alpha=alpha, linestyle=linestyle)
    elif geom.geom_type == "LineString":
        x, y = geom.xy
        ax.plot(x, y, color=color, linewidth=linewidth, alpha=alpha, linestyle=linestyle)


def _set_bounds(ax, boundary=None, features=None):
    """Set axis bounds from boundary or features."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    bounds = None
    if boundary and boundary.get("features"):
        try:
            g = shape(boundary["features"][0]["geometry"])
            bounds = g.bounds
        except Exception:
            pass

    if bounds is None and features:
        try:
            geoms = [shape(f["geometry"]) for f in features
                     if f.get("geometry", {}).get("coordinates")]
            if geoms:
                bounds = unary_union(geoms).bounds
        except Exception:
            pass

    if bounds:
        minx, miny, maxx, maxy = bounds
        margin = (maxx - minx) * 0.03
        ax.set_xlim(minx - margin, maxx + margin)
        ax.set_ylim(miny - margin, maxy + margin)

    ax.set_aspect("equal")


def _add_legend(ax, color_map, loc="upper right", fontsize=7):
    """Add color legend from mapping."""
    import matplotlib.patches as mpatches
    patches = [
        mpatches.Patch(color=v["fill"], label=v.get("label", k), alpha=0.7)
        for k, v in color_map.items()
    ]
    if patches:
        ax.legend(handles=patches, loc=loc, fontsize=fontsize)


# ── Layer-specific renderers ──────────────────────────────────

def render_planning_zone(
    configs: List[Dict], boundary: Optional[Dict], output_path: str,
):
    """Render planning_zone layer with 4-zone allocation colors + change highlights."""
    plt = _setup_matplotlib()
    from shapely.geometry import shape

    config = next((c for c in configs if c.get("layerType") == "planning_zone"), None)
    if not config:
        print("[Skip] No planning_zone layer found")
        return

    fig, ax = plt.subplots(1, 1, figsize=(14, 10))
    features = config.get("geojson", {}).get("features", [])

    stats = {}
    for feat in features:
        geom_dict = feat.get("geometry", {})
        props = feat.get("properties", {})
        if not geom_dict or not geom_dict.get("coordinates"):
            continue

        try:
            geom = shape(geom_dict)
        except Exception:
            continue

        zone_type = props.get("zone_type", "") or props.get("assigned_zone", "")
        color_def = PLANNING_ZONE_MPL.get(zone_type, {"fill": "#CCCCCC", "stroke": "#666666"})

        changed = props.get("changed", False)
        hatch = "///" if changed else None
        edgecolor = "#FF0000" if changed else color_def["stroke"]
        linewidth = 1.5 if changed else 0.8

        _draw_polygons(ax, geom, color_def["fill"], edgecolor,
                       alpha=0.45, linewidth=linewidth, hatch=hatch)

        stats[zone_type] = stats.get(zone_type, 0) + props.get("area_ha", 0)

    _set_bounds(ax, boundary=boundary, features=features)
    _add_legend(ax, PLANNING_ZONE_MPL)

    # Stats annotation
    stats_text = "\n".join(f"{k}: {v:.1f} ha" for k, v in sorted(stats.items()))
    ax.text(0.02, 0.02, stats_text, transform=ax.transAxes,
            fontsize=8, verticalalignment="bottom",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    ax.set_title("Planning Zone Allocation (4-zone)", fontsize=14)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] planning_zone → {output_path}")


def render_function_zone(
    configs: List[Dict], boundary: Optional[Dict], output_path: str,
):
    """Render function_zone layer with DLBM-reclassified colors."""
    plt = _setup_matplotlib()
    from shapely.geometry import shape

    config = next((c for c in configs if c.get("layerType") == "function_zone"), None)
    if not config:
        print("[Skip] No function_zone layer found")
        return

    fig, ax = plt.subplots(1, 1, figsize=(14, 10))
    features = config.get("geojson", {}).get("features", [])

    for feat in features:
        geom_dict = feat.get("geometry", {})
        props = feat.get("properties", {})
        if not geom_dict or not geom_dict.get("coordinates"):
            continue

        try:
            geom = shape(geom_dict)
        except Exception:
            continue

        land_use = props.get("land_use", "")
        color_def = FUNCTION_ZONE_MPL.get(land_use, {"fill": "#CCCCCC", "stroke": "#666666"})
        fill = props.get("color") or color_def["fill"]
        stroke = props.get("stroke") or color_def["stroke"]

        _draw_polygons(ax, geom, fill, stroke, alpha=0.5)

    _set_bounds(ax, boundary=boundary, features=features)
    _add_legend(ax, FUNCTION_ZONE_MPL)
    ax.set_title("Function Zone (DLBM Classification)", fontsize=14)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] function_zone → {output_path}")


def render_comparison(
    configs: List[Dict], boundary: Optional[Dict], output_path: str,
):
    """Side-by-side comparison: function_zone (current) vs planning_zone (planned)."""
    plt = _setup_matplotlib()
    from shapely.geometry import shape

    func_cfg = next((c for c in configs if c.get("layerType") == "function_zone"), None)
    plan_cfg = next((c for c in configs if c.get("layerType") == "planning_zone"), None)

    if not func_cfg and not plan_cfg:
        print("[Skip] No function_zone or planning_zone for comparison")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(24, 10))

    # Left: function_zone (current)
    if func_cfg:
        for feat in func_cfg.get("geojson", {}).get("features", []):
            geom_dict = feat.get("geometry", {})
            props = feat.get("properties", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                continue
            try:
                geom = shape(geom_dict)
            except Exception:
                continue
            land_use = props.get("land_use", "")
            cdef = FUNCTION_ZONE_MPL.get(land_use, {"fill": "#CCCCCC", "stroke": "#666666"})
            _draw_polygons(ax1, geom, props.get("color") or cdef["fill"],
                           props.get("stroke") or cdef["stroke"], alpha=0.5)
        _add_legend(ax1, FUNCTION_ZONE_MPL, loc="upper right")
    ax1.set_title("Current (Function Zone)", fontsize=13)
    _set_bounds(ax1, boundary=boundary)

    # Right: planning_zone (planned)
    if plan_cfg:
        for feat in plan_cfg.get("geojson", {}).get("features", []):
            geom_dict = feat.get("geometry", {})
            props = feat.get("properties", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                continue
            try:
                geom = shape(geom_dict)
            except Exception:
                continue
            zt = props.get("zone_type", "") or props.get("assigned_zone", "")
            cdef = PLANNING_ZONE_MPL.get(zt, {"fill": "#CCCCCC", "stroke": "#666666"})
            changed = props.get("changed", False)
            _draw_polygons(ax2, geom, cdef["fill"],
                           "#FF0000" if changed else cdef["stroke"],
                           alpha=0.45, linewidth=1.2 if changed else 0.8,
                           hatch="///" if changed else None)
        _add_legend(ax2, PLANNING_ZONE_MPL, loc="upper right")
    ax2.set_title("Planned (Planning Zone) — red = changed", fontsize=13)
    _set_bounds(ax2, boundary=boundary)

    plt.suptitle("Current vs Planned Layout Comparison", fontsize=15, y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] comparison → {output_path}")


def render_composite(
    configs: List[Dict], boundary: Optional[Dict], output_path: str,
):
    """Composite map: all layers stacked with correct priority."""
    plt = _setup_matplotlib()
    from shapely.geometry import shape

    LAYER_ORDER = [
        "boundary", "sensitivity_zone", "function_zone",
        "planning_zone", "development_axis", "infrastructure",
        "facility_point",
    ]

    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    all_features = []

    for layer_type in LAYER_ORDER:
        config = next((c for c in configs if c.get("layerType") == layer_type), None)
        if not config:
            continue

        geojson = config.get("geojson", {})
        features = geojson.get("features", [])
        all_features.extend(features)

        for feat in features:
            geom_dict = feat.get("geometry", {})
            props = feat.get("properties", {})
            if not geom_dict or not geom_dict.get("coordinates"):
                continue

            try:
                geom = shape(geom_dict)
            except Exception:
                continue

            if layer_type == "boundary":
                if geom.geom_type in ("Polygon", "MultiPolygon"):
                    exterior = geom.exterior if geom.geom_type == "Polygon" else geom.geoms[0].exterior
                    x, y = exterior.xy
                    ax.plot(x, y, color="#333333", linewidth=2, alpha=0.8)

            elif layer_type == "function_zone":
                land_use = props.get("land_use", "")
                cdef = FUNCTION_ZONE_MPL.get(land_use, {"fill": "#CCCCCC", "stroke": "#666666"})
                _draw_polygons(ax, geom, props.get("color") or cdef["fill"],
                               props.get("stroke") or cdef["stroke"], alpha=0.35)

            elif layer_type == "planning_zone":
                zt = props.get("zone_type", "") or props.get("assigned_zone", "")
                cdef = PLANNING_ZONE_MPL.get(zt, {"fill": "#CCCCCC", "stroke": "#666666"})
                changed = props.get("changed", False)
                _draw_polygons(ax, geom, cdef["fill"],
                               "#FF0000" if changed else cdef["stroke"],
                               alpha=0.3, linewidth=1.0,
                               hatch="///" if changed else None)

            elif layer_type == "development_axis":
                axis_type = props.get("axis_type", "secondary")
                color = "#FF0000" if axis_type == "primary" else "#00AA00"
                lw = 2.5 if axis_type == "primary" else 1.5
                label = props.get("label", "")
                if geom.geom_type == "LineString":
                    _draw_linestring(ax, geom, color, linewidth=lw)
                elif geom.geom_type == "Point":
                    ax.plot(geom.x, geom.y, "o", color=color, markersize=8)
                    if label:
                        ax.annotate(label, (geom.x, geom.y), fontsize=7,
                                    xytext=(5, 5), textcoords="offset points")

            elif layer_type == "facility_point":
                status = props.get("status", "existing")
                ftype = props.get("facility_type", "")
                fc = FACILITY_MPL.get(status, {"fill": "blue", "stroke": "#00008B"})
                if geom.geom_type == "Point":
                    ax.plot(geom.x, geom.y, "s", color=fc["fill"], markersize=6)
                    if ftype:
                        ax.annotate(ftype, (geom.x, geom.y), fontsize=5,
                                    xytext=(4, 4), textcoords="offset points")

            elif layer_type == "infrastructure":
                if geom.geom_type == "LineString":
                    _draw_linestring(ax, geom, "#666666", linewidth=1, alpha=0.6)

            elif layer_type == "sensitivity_zone":
                level = props.get("sensitivity_level", "low")
                s_color = {"high": "#FF4444", "medium": "#FFAA00", "low": "#44AA44"}.get(level, "#CCCCCC")
                _draw_polygons(ax, geom, s_color, "#333333", alpha=0.2, linewidth=0.3)

    _set_bounds(ax, boundary=boundary, features=all_features)

    # Combined legend
    import matplotlib.patches as mpatches
    legend_items = []
    for name, cdef in PLANNING_ZONE_MPL.items():
        legend_items.append(mpatches.Patch(color=cdef["fill"], label=cdef["label"], alpha=0.5))
    legend_items.append(mpatches.Patch(facecolor="white", edgecolor="red",
                                        hatch="///", label="Changed parcel"))
    ax.legend(handles=legend_items, loc="upper right", fontsize=7)

    ax.set_title("Composite Layout — All Layers", fontsize=14)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] composite → {output_path}")


# ── Stats report ──────────────────────────────────────────────

def print_stats(configs: List[Dict], boundary_area_ha: float = 0):
    """Print layer statistics to console."""
    print("\n" + "=" * 65)
    print("LAYER STATISTICS")
    print("=" * 65)

    for config in configs:
        layer_type = config.get("layerType", "unknown")
        features = config.get("geojson", {}).get("features", [])
        feat_count = len(features)

        if feat_count == 0:
            print(f"  {layer_type}: 0 features")
            continue

        total_area = sum(f.get("properties", {}).get("area_ha", 0) for f in features)
        print(f"  {layer_type}: {feat_count} features, {total_area:.1f} ha")

        if layer_type == "planning_zone":
            by_zone = {}
            for f in features:
                props = f.get("properties", {})
                zt = props.get("zone_type", "") or props.get("assigned_zone", "")
                area = props.get("area_ha", 0)
                changed = "changed" if props.get("changed") else "unchanged"
                by_zone.setdefault(zt, {"area": 0, "count": 0, "changed": 0})
                by_zone[zt]["area"] += area
                by_zone[zt]["count"] += 1
                if changed == "changed":
                    by_zone[zt]["changed"] += 1

            print(f"    {'Zone Type':<20s} {'Area (ha)':>10s} {'Count':>6s} {'Changed':>8s}")
            for zt, info in sorted(by_zone.items(), key=lambda x: -x[1]["area"]):
                print(f"    {zt:<20s} {info['area']:>10.1f} {info['count']:>6d} {info['changed']:>8d}")

        elif layer_type == "function_zone":
            by_use = {}
            for f in features:
                props = f.get("properties", {})
                lu = props.get("land_use", "")
                area = props.get("area_ha", 0)
                target = props.get("target_ratio", 0)
                actual = props.get("area_ratio", 0)
                by_use[lu] = {"area": area, "target": target, "actual": actual}
            print(f"    {'Land Use':<16s} {'Area (ha)':>10s} {'Target':>8s} {'Actual':>8s}")
            for lu, info in sorted(by_use.items(), key=lambda x: -x[1]["area"]):
                print(f"    {lu:<16s} {info['area']:>10.1f} {info['target']:>7.1%} {info['actual']:>7.1%}")

    if boundary_area_ha > 0:
        func_cfg = next((c for c in configs if c.get("layerType") == "function_zone"), None)
        if func_cfg:
            func_area = sum(
                f.get("properties", {}).get("area_ha", 0)
                for f in func_cfg.get("geojson", {}).get("features", [])
            )
            err = abs(func_area - boundary_area_ha) / boundary_area_ha * 100
            print(f"\n  Area validation: {func_area:.1f} ha vs {boundary_area_ha:.1f} ha boundary "
                  f"(error {err:.2f}%)")

    print("=" * 65)


def _extract_village_name(reports: Dict) -> str:
    """Extract village name from reports, fallback to default."""
    import re
    loc = reports.get("location", {})
    summary = loc.get("summary", {})
    text = summary.get("text_summary", "")
    if text:
        m = re.search(r"([^\s，。]+(?:村|社区|组))", text)
        if m:
            return m.group(1)
    return "金田村"


async def parse_intent_via_llm(
    reports: Dict, village_name: str, gis_data: Optional[Dict] = None
) -> UnifiedSpatialIntent:
    """Call LLM to parse reports into UnifiedSpatialIntent."""
    from app.tools.gis.layout_tools import _aparse_reports_to_intent, _output_to_intent
    from app.modules.parsing.schemas import IntentOutput

    result = await _aparse_reports_to_intent(
        reports=reports, village_name=village_name, gis_data=gis_data
    )

    if not result.get("success"):
        raise RuntimeError(f"LLM parse failed: {result.get('error', 'unknown')}")

    intent_output = IntentOutput.model_validate(result["data"]["intent_json"])
    intent = _output_to_intent(intent_output)

    print(f"LLM parse: {result['data']['zone_count']} zones, "
          f"{result['data']['facility_count']} facilities, "
          f"{result['data']['axis_count']} axes")
    print(f"  zones: {result['data']['zones']}")
    print(f"  anchor_confidence: {result['data'].get('anchor_confidence', 'N/A')}")

    return intent


def _build_intent_from_dlbm(landuse: Optional[Dict]) -> UnifiedSpatialIntent:
    """Lightweight DLBM fallback — only zone area ratios, engine infers the rest."""
    if not landuse:
        return UnifiedSpatialIntent(zones=[], facilities=[], axes=[],
                                    constraints=[], metadata={})

    from app.modules.gis.schema import get_zone_type_for_dlbm

    zone_counts: Dict[str, float] = {}
    total = 0.0
    for feat in landuse.get("features", []):
        props = feat.get("properties", {})
        dlbm = str(props.get("DLBM", ""))
        mj = props.get("DLMJ")
        if not dlbm or mj is None:
            continue
        try:
            area = float(mj)
            zt = get_zone_type_for_dlbm(dlbm)
            zone_counts[zt] = zone_counts.get(zt, 0.0) + area
            total += area
        except (ValueError, TypeError):
            continue

    if total <= 0:
        return UnifiedSpatialIntent(zones=[], facilities=[], axes=[],
                                    constraints=[], metadata={})

    zones = [
        ZoneIntent(zone_id=f"Z_{i+1}", land_use=zt, dlbm="",
                   area_ratio=round(area / total, 4),
                   direction=Direction.CENTER, density=Density.MEDIUM,
                   preserve_existing=True)
        for i, (zt, area) in enumerate(sorted(zone_counts.items(),
                                               key=lambda x: -x[1]))
    ]
    return UnifiedSpatialIntent(zones=zones, facilities=[], axes=[],
                                constraints=[], metadata={"source": "dlbm_fallback"})


# ── Main ──────────────────────────────────────────────────────

def main():
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description="Render planning layout layers")
    parser.add_argument("--output", default="test-screenshots", help="Output directory")
    args = parser.parse_args()

    reports, boundary, landuse, roads = load_all()
    print(f"Loaded: {len(reports)} reports, "
          f"boundary={len(boundary.get('features', [])) if boundary else 0} feats, "
          f"landuse={len(landuse.get('features', [])) if landuse else 0} feats")

    if not reports:
        print("No reports found in DB, exiting")
        return

    village_name = _extract_village_name(reports)
    gis_data = {
        "landuse_current_geojson": landuse,
        "boundary_current_geojson": boundary,
    }

    # Primary: LLM parsing from reports
    try:
        print(f"Parsing reports via LLM (village={village_name})...")
        intent = asyncio.run(parse_intent_via_llm(reports, village_name, gis_data))
    except Exception as e:
        print(f"LLM parse failed: {e}")
        print("Falling back to DLBM statistics")
        intent = _build_intent_from_dlbm(landuse)

    print(f"Intent: {len(intent.zones)} zones, "
          f"{len(intent.facilities)} facilities, "
          f"{len(intent.axes)} axes")

    # Generate layout via service layer
    kg = PlanningKG(village_name="金田村")
    kg.build_from_reports(reports, landuse)

    all_layers = {}
    zg = ZoneGenerator()
    func_zones = zg.generate(intent, landuse, boundary, {"landuse_current_geojson": landuse, "boundary_geojson": boundary, "road_geojson": roads})
    if func_zones:
        all_layers["function_zone"] = func_zones
    fp = FacilityPlacer()
    facilities = fp.place(
        facilities=intent.facilities if hasattr(intent, "facilities") else [],
        landuse_geojson=landuse, boundary_geojson=boundary,
    )
    if facilities and facilities.get("features"):
        all_layers["facility_point"] = facilities
    ab = AxisBuilder()
    axes = ab.build(intent, boundary, landuse)
    if axes and axes.get("features"):
        all_layers["development_axis"] = axes
    mr = MapRenderer()
    configs = mr.render(all_layers, boundary)

    print(f"Layout: {len(configs)} layers")
    for c in configs:
        fc = len(c.get("geojson", {}).get("features", []))
        print(f"  {c['layerType']}: {fc} features")

    # Output dir
    out_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", args.output
    ))
    os.makedirs(out_dir, exist_ok=True)

    # Render each view
    render_planning_zone(configs, boundary, os.path.join(out_dir, "layout_planning_zone.png"))
    render_function_zone(configs, boundary, os.path.join(out_dir, "layout_function_zone.png"))
    render_comparison(configs, boundary, os.path.join(out_dir, "layout_comparison.png"))
    render_composite(configs, boundary, os.path.join(out_dir, "layout_composite.png"))

    # Stats
    boundary_area = 0
    if boundary and boundary.get("features"):
        try:
            from shapely.geometry import shape
            g = shape(boundary["features"][0]["geometry"])
            import geopandas as gpd
            boundary_area = gpd.GeoSeries([g], crs="EPSG:4326").to_crs("EPSG:3857")[0].area / 10000
        except Exception:
            pass

    print_stats(configs, boundary_area)

    # Save layout configs JSON
    configs_path = os.path.join(out_dir, "layout_configs.json")
    configs_summary = []
    for c in configs:
        cs = {k: v for k, v in c.items() if k != "geojson"}
        fc = c.get("geojson", {}).get("features", [])
        cs["feature_count"] = len(fc)
        if c.get("layerType") in ("function_zone", "planning_zone"):
            cs["zones"] = [
                {k: v for k, v in f.get("properties", {}).items()
                 if k in ("zone_id", "land_use", "zone_type", "assigned_zone",
                           "area_ha", "area_ratio", "target_ratio", "changed")}
                for f in fc
            ]
        configs_summary.append(cs)

    with open(configs_path, "w", encoding="utf-8") as f:
        json.dump(configs_summary, f, ensure_ascii=False, indent=2)
    print(f"[Save] Configs → {configs_path}")

    print(f"\nDone. {len(configs)} layers rendered to {out_dir}/")


if __name__ == "__main__":
    main()
