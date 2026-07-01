"""Visual validation: render layout results as matplotlib map.

Generates PNG images comparing:
1. Parsed intent zones (from DB reports) vs default zones
2. Zone classification with DLBM-based parcel data
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database.engine import get_db_path
from app.tools.gis.layout_tools import _parse_reports_to_intent, _dict_to_intent
from app.services.modules.gis.layout.engine import SpatialLayoutEngine

import sqlite3


def load_all():
    """Load DB reports + GIS data."""
    # DB reports
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT session_id FROM dimension_reports WHERE layer=3 "
        "ORDER BY generated_at DESC LIMIT 1"
    )
    row = cur.fetchone()
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

    # GIS data
    project_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    data_dir = os.path.join(project_root, "docs", "gis", "jintian_boundary")

    boundary = None
    landuse = None
    roads = None

    bf = os.path.join(data_dir, "boundary_current.geojson")
    if os.path.exists(bf):
        with open(bf, "r", encoding="utf-8") as f:
            boundary = json.load(f)

    lf = os.path.join(data_dir, "landuse_current.geojson")
    if os.path.exists(lf):
        with open(lf, "r", encoding="utf-8") as f:
            landuse = json.load(f)

    rf = os.path.join(data_dir, "roads_osm.geojson")
    if not os.path.exists(rf):
        rf = os.path.join(data_dir, "road_current.geojson")
    if os.path.exists(rf):
        with open(rf, "r", encoding="utf-8") as f:
            roads = json.load(f)

    return reports, boundary, landuse, roads


def render_layout(configs, boundary, output_path, title="Layout"):
    """Render GISLayerConfig list as matplotlib map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.collections import PatchCollection
    from shapely import from_geojson as shapely_from_geojson
    from shapely.geometry import shape
    import numpy as np

    fig, ax = plt.subplots(1, 1, figsize=(14, 10))

    # Colors by layer type
    layer_colors = {
        "boundary": "#333333",
        "function_zone": None,  # per-feature color
        "planning_zone": None,
        "sensitivity_zone": "#FF6600",
        "development_axis": "#FF0000",
        "infrastructure": "#666666",
        "facility_point": "#0000FF",
    }

    zone_colors_map = {
        "生态绿地": "#228B22",
        "农业用地": "#F0C040",
        "居住用地": "#FF4444",
        "交通用地": "#AAAAAA",
        "水域": "#4488FF",
        "公共服务用地": "#FF8800",
        "产业用地": "#8B008B",
    }

    for config in configs:
        layer_type = config.get("layerType", "")
        geojson = config.get("geojson", {})
        features = geojson.get("features", [])

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
                    x, y = geom.exterior.xy if geom.geom_type == "Polygon" else geom.geoms[0].exterior.xy
                    ax.plot(x, y, color="#333333", linewidth=2, alpha=0.8)

            elif layer_type == "function_zone":
                land_use = props.get("land_use", "")
                color = props.get("color") or zone_colors_map.get(land_use, "#CCCCCC")

                if geom.geom_type == "Polygon":
                    patch = MplPolygon(list(geom.exterior.coords), closed=True,
                                       facecolor=color, edgecolor="black",
                                       alpha=0.5, linewidth=0.5)
                    ax.add_patch(patch)
                elif geom.geom_type == "MultiPolygon":
                    for poly in geom.geoms:
                        patch = MplPolygon(list(poly.exterior.coords), closed=True,
                                           facecolor=color, edgecolor="black",
                                           alpha=0.5, linewidth=0.5)
                        ax.add_patch(patch)

            elif layer_type == "development_axis":
                axis_type = props.get("axis_type", "secondary")
                color = "#FF0000" if axis_type == "primary" else "#00AA00"
                if geom.geom_type == "LineString":
                    x, y = geom.xy
                    ax.plot(x, y, color=color, linewidth=2, alpha=0.8)
                elif geom.geom_type == "Point":
                    ax.plot(geom.x, geom.y, 'o', color=color, markersize=8)

            elif layer_type == "facility_point":
                if geom.geom_type == "Point":
                    ax.plot(geom.x, geom.y, 's', color="blue", markersize=6)
                    name = props.get("facility_type", props.get("name", ""))
                    ax.annotate(name, (geom.x, geom.y), fontsize=6,
                                xytext=(5, 5), textcoords="offset points")

            elif layer_type == "infrastructure":
                if geom.geom_type == "LineString":
                    x, y = geom.xy
                    ax.plot(x, y, color="#666666", linewidth=1, alpha=0.6)

    # Set bounds from boundary
    if boundary and boundary.get("features"):
        try:
            boundary_geom = shape(boundary["features"][0]["geometry"])
            minx, miny, maxx, maxy = boundary_geom.bounds
            margin = (maxx - minx) * 0.05
            ax.set_xlim(minx - margin, maxx + margin)
            ax.set_ylim(miny - margin, maxy + margin)
        except Exception:
            pass

    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")

    # Add legend for zone types
    import matplotlib.patches as mpatches
    legend_patches = [
        mpatches.Patch(color=c, label=l, alpha=0.6)
        for l, c in zone_colors_map.items()
    ]
    ax.legend(handles=legend_patches, loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] Saved to {output_path}")


def render_parcels(landuse, output_path, title="Current Land Use (DLBM)"):
    """Render raw landuse parcels colored by DLBM zone type."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon
    from shapely.geometry import shape
    from app.services.modules.gis.layout.zone_generator import resolve_zone_type_for_dlbm

    zone_colors = {
        "生态绿地": "#228B22",
        "农业用地": "#F0C040",
        "居住用地": "#FF4444",
        "交通用地": "#AAAAAA",
        "水域": "#4488FF",
        "公共服务用地": "#FF8800",
        "产业用地": "#8B008B",
    }

    fig, ax = plt.subplots(1, 1, figsize=(14, 10))

    for feat in landuse.get("features", []):
        geom_dict = feat.get("geometry", {})
        props = feat.get("properties", {})
        if not geom_dict or not geom_dict.get("coordinates"):
            continue

        try:
            geom = shape(geom_dict)
        except Exception:
            continue

        dlbm = str(props.get("DLBM", "")).strip()
        zone_type = resolve_zone_type_for_dlbm(dlbm)
        color = zone_colors.get(zone_type, "#CCCCCC")

        if geom.geom_type == "Polygon":
            patch = MplPolygon(list(geom.exterior.coords), closed=True,
                               facecolor=color, edgecolor="none",
                               alpha=0.7, linewidth=0)
            ax.add_patch(patch)
        elif geom.geom_type == "MultiPolygon":
            for poly in geom.geoms:
                patch = MplPolygon(list(poly.exterior.coords), closed=True,
                                   facecolor=color, edgecolor="none",
                                   alpha=0.7, linewidth=0)
                ax.add_patch(patch)

    # Compute bounds
    all_geoms = []
    for feat in landuse.get("features", []):
        try:
            g = shape(feat["geometry"])
            all_geoms.append(g)
        except Exception:
            continue
    if all_geoms:
        from shapely.ops import unary_union
        union = unary_union(all_geoms)
        minx, miny, maxx, maxy = union.bounds
        margin = (maxx - minx) * 0.02
        ax.set_xlim(minx - margin, maxx + margin)
        ax.set_ylim(miny - margin, maxy + margin)

    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")

    import matplotlib.patches as mpatches
    legend_patches = [
        mpatches.Patch(color=c, label=l, alpha=0.7)
        for l, c in zone_colors.items()
    ]
    ax.legend(handles=legend_patches, loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Render] Saved to {output_path}")


def main():
    reports, boundary, landuse, roads = load_all()
    print(f"Loaded {len(reports)} reports, "
          f"boundary={len(boundary.get('features', [])) if boundary else 0} feats, "
          f"landuse={len(landuse.get('features', [])) if landuse else 0} feats")

    # Parse intent
    result = _parse_reports_to_intent(reports=reports, village_name="金田村")
    if not result.get("success"):
        print(f"Parse failed: {result.get('error')}")
        return

    intent_json = result["data"]["intent_json"]
    print(f"Intent: {result['data']['zone_count']} zones, "
          f"{result['data']['facility_count']} facilities, "
          f"{result['data']['axis_count']} axes")

    # Generate layout
    intent = _dict_to_intent(intent_json)
    engine = SpatialLayoutEngine()
    configs = engine.generate_layout(
        intent=intent,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
        road_geojson=roads,
    )

    print(f"Layout: {len(configs)} layers")
    for c in configs:
        feat_count = len(c.get("geojson", {}).get("features", []))
        print(f"  {c['layerType']}: {feat_count} features")

    # Output dir
    out_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "test-screenshots"
    ))
    os.makedirs(out_dir, exist_ok=True)

    # Render 1: Parsed intent layout
    render_layout(
        configs, boundary,
        os.path.join(out_dir, "layout_parsed_intent.png"),
        title=f"Parsed Intent Layout ({len(intent.zones)} zones)"
    )

    # Render 2: Current land use parcels
    if landuse:
        render_parcels(
            landuse,
            os.path.join(out_dir, "layout_current_landuse.png"),
            title="Current Land Use (660 parcels)"
        )

    # Save layout configs
    configs_path = os.path.join(out_dir, "layout_configs.json")
    # Strip geojson from configs for readability
    configs_summary = []
    for c in configs:
        cs = {k: v for k, v in c.items() if k != "geojson"}
        cs["feature_count"] = len(c.get("geojson", {}).get("features", []))
        # Add zone summary for function_zone
        if c.get("layerType") == "function_zone":
            zones_info = []
            for feat in c.get("geojson", {}).get("features", []):
                props = feat.get("properties", {})
                zones_info.append({
                    "land_use": props.get("land_use"),
                    "area_ha": props.get("area_ha"),
                    "target_ratio": props.get("target_ratio"),
                    "actual_ratio": props.get("area_ratio"),
                })
            cs["zones"] = zones_info
        configs_summary.append(cs)

    with open(configs_path, "w", encoding="utf-8") as f:
        json.dump(configs_summary, f, ensure_ascii=False, indent=2)
    print(f"[Save] Configs summary saved to {configs_path}")

    # Feasibility assessment
    print("\n" + "=" * 60)
    print("FEASIBILITY ASSESSMENT")
    print("=" * 60)

    # Check zone coverage
    function_zone_config = next((c for c in configs if c.get("layerType") == "function_zone"), None)
    if function_zone_config:
        total_area_ha = 0
        for feat in function_zone_config.get("geojson", {}).get("features", []):
            total_area_ha += feat.get("properties", {}).get("area_ha", 0)

        print(f"Total function zone area: {total_area_ha:.2f} ha")
        print(f"Expected (boundary): ~2868 ha")

        for feat in function_zone_config.get("geojson", {}).get("features", []):
            props = feat.get("properties", {})
            print(f"  Zone {props.get('zone_id')}: {props.get('land_use')} "
                  f"= {props.get('area_ha', 0):.2f} ha "
                  f"(target: {props.get('target_ratio', 0):.1%}, "
                  f"actual: {props.get('area_ratio', 0):.1%})")

    print("\nAssessment: PASS" if len(configs) >= 3 else "Assessment: NEEDS WORK")
    print(f"  Layer count: {len(configs)} (target: >=3)")
    print(f"  Has boundary: {'Yes' if any(c['layerType']=='boundary' for c in configs) else 'No'}")
    print(f"  Has function_zone: {'Yes' if function_zone_config else 'No'}")
    if function_zone_config:
        print(f"  Zone features: {function_zone_config.get('feature_count', 0)}")


if __name__ == "__main__":
    main()
