"""Layout pipeline executor — shared by API routes and tools.

Runs the full KG → Conflict → Allocate → Generate pipeline for a village,
producing GIS layers from a spatial intent.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_layout_pipeline(
    intent: Dict[str, Any],
    gis_data: Dict[str, Any],
    village_name: str = "金田村委会",
    *,
    run_kg: bool = True,
    run_conflict: bool = True,
    run_allocate: bool = True,
    run_generate: bool = True,
    run_export: bool = True,
    run_render: bool = True,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the full spatial layout pipeline.

    Steps: KG → Conflict → MIP Allocate → Generate Layers → Export → Render

    Args:
        intent: UnifiedSpatialIntent as dict (zones, facilities, axes, constraints).
        gis_data: load_all() output with boundary, landuse, etc.
        village_name: target village name.
        run_kg/run_conflict/run_allocate/run_generate: toggle pipeline steps.
        run_export/run_render: toggle output steps.
        output_dir: base directory for export/render outputs.

    Returns:
        Dict with keys: kg, conflict, allocation, layers, layer_summary, export, render.
    """
    result: Dict[str, Any] = {}
    landuse_geojson = gis_data.get("landuse_current_geojson")

    # ── Step 1: KG ──────────────────────────────────────────────
    kg_constraints: List[Dict[str, Any]] = []
    kg = None
    if run_kg:
        try:
            from app.modules.kg.manager import get_kg_manager
            from app.modules.data.catalog import DataCatalog
            manager = get_kg_manager()
            bundle = None
            try:
                bundle = DataCatalog().load_village_bundle(village_name)
            except Exception:
                pass
            kg = manager.get_or_build_kg(
                village_name=village_name,
                bundle=bundle,
                intent=intent,
            )
            kg_constraints = kg.get_constraints()
            result["kg"] = {
                "triple_count": kg.get_triple_count(),
                "constraint_count": len(kg_constraints),
            }
        except Exception as e:
            result["kg"] = {"error": str(e)}

    # ── Step 2: Conflict ────────────────────────────────────────
    if run_conflict:
        try:
            from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
            from app.tools.gis._conflict.detector import ConflictDetector
            from app.tools.gis._conflict.resolver import ConflictResolver

            summaries = GISMetricsCalculator.compute_summaries(gis_data)
            conflict_report = ConflictDetector().detect_all(summaries)
            resolution_report = ConflictResolver().resolve(conflict_report)
            result["conflict"] = {
                "metric_conflicts": len(conflict_report.metric_conflicts) if hasattr(conflict_report, "metric_conflicts") else 0,
                "constraint_violations": len(conflict_report.constraint_violations) if hasattr(conflict_report, "constraint_violations") else 0,
                "resolved_values": resolution_report.resolved_values if hasattr(resolution_report, "resolved_values") else {},
            }
        except Exception as e:
            result["conflict"] = {"error": str(e)}

    # ── Step 3: MIP Allocate ────────────────────────────────────
    allocated_geojson = None
    if run_allocate:
        try:
            from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
            from .optimizer.mip_allocator import MIPZoneAllocator

            metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
            total_area_ha = metrics["total_area_ha"]
            targets = {}
            for z in intent.get("zones", []):
                lu, ratio = z.get("land_use", ""), z.get("area_ratio", 0)
                if lu and ratio:
                    targets[lu] = ratio * total_area_ha

            if targets and landuse_geojson:
                allocator = MIPZoneAllocator()
                allocated_geojson, mip_trace = allocator.solve(
                    landuse_geojson=landuse_geojson,
                    targets=targets,
                    constraints=kg_constraints or None,
                    kg=kg,
                )
                result["allocation"] = {
                    "mode": mip_trace.get("mode", "unknown"),
                    "changed_pct": mip_trace.get("changed_pct", 0),
                    "solver_status": mip_trace.get("solver_status", "unknown"),
                }
            else:
                result["allocation"] = {"mode": "skipped", "reason": "no targets or landuse data"}
        except Exception as e:
            result["allocation"] = {"mode": "failed", "error": str(e)}

    # ── Step 4: Generate Layers ─────────────────────────────────
    if run_generate:
        from app.tools.gis.generate import (
            _generate_function_zones,
            _make_planning_zone_layer,
            _generate_facilities,
            _generate_axes,
            _generate_space_control_zone,
            _generate_land_use_zone,
        )

        layers: List[Dict[str, Any]] = []
        fz = _generate_function_zones(intent, gis_data)
        if fz:
            layers.append(fz)
        pz = _make_planning_zone_layer(allocated_geojson, gis_data)
        if pz:
            layers.append(pz)
        fp = _generate_facilities(intent, gis_data)
        if fp:
            layers.append(fp)
        ax = _generate_axes(intent, gis_data)
        if ax:
            layers.append(ax)
        sc = _generate_space_control_zone(gis_data, allocated_geojson, intent)
        if sc:
            layers.append(sc)
        lu = _generate_land_use_zone(allocated_geojson, gis_data)
        if lu:
            layers.append(lu)

        result["layers"] = layers
        result["layer_summary"] = [
            {"layerType": lyr.get("layerType"), "feature_count": len(lyr.get("data", {}).get("features", []))}
            for lyr in layers
        ]

    # ── Step 5: Export ──────────────────────────────────────────
    if run_export and result.get("layers"):
        base = Path(output_dir) if output_dir else Path("output") / village_name
        try:
            result["export"] = _run_export_step(
                layers=result["layers"], gis_data=gis_data, output_dir=base, village_name=village_name,
            )
        except Exception as e:
            result["export"] = {"error": str(e)}

    # ── Step 6: Render ──────────────────────────────────────────
    if run_render and result.get("layers"):
        render_dir = Path(output_dir) / "comparison" if output_dir else Path("output") / f"{village_name}_comparison"
        try:
            result["render"] = _run_render_step(
                layers=result["layers"], gis_data=gis_data,
                output_dir=render_dir, village_name=village_name,
            )
        except Exception as e:
            result["render"] = {"error": str(e)}

    return result


# ── Export / Render helpers (extracted from gis_test_routes.py) ──


def _run_export_step(
    layers: List[Dict[str, Any]],
    gis_data: Dict[str, Any],
    output_dir: Any,
    village_name: str,
) -> Dict[str, Any]:
    """Export all layers as GeoJSON files to output directory."""
    import json as _json

    export_dir = Path(output_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    for lyr in layers:
        layer_type = lyr.get("layerType", "unknown")
        geojson = lyr.get("data")
        if not geojson or not geojson.get("features"):
            continue
        filepath = export_dir / f"{layer_type}.geojson"
        with open(filepath, "w", encoding="utf-8") as f:
            _json.dump(geojson, f, ensure_ascii=False)
        exported.append(str(filepath))

    for key, name in [
        ("boundary_geojson", "boundary"),
        ("landuse_current_geojson", "current_landuse"),
        ("road_geojson", "current_road"),
        ("farmland_protection_geojson", "farmland_protection"),
        ("ecological_protection_geojson", "ecological_protection"),
    ]:
        geojson = gis_data.get(key)
        if geojson and geojson.get("features"):
            filepath = export_dir / f"{name}.geojson"
            with open(filepath, "w", encoding="utf-8") as f:
                _json.dump(geojson, f, ensure_ascii=False)
            exported.append(str(filepath))

    from app.tools.gis.export import _compute_land_balance
    landuse = gis_data.get("landuse_current_geojson")
    if landuse:
        balance = _compute_land_balance(landuse)
        balance_path = export_dir / "land_balance.json"
        with open(balance_path, "w", encoding="utf-8") as f:
            _json.dump(balance, f, ensure_ascii=False, indent=2)
        exported.append(str(balance_path))

    return {"exported_files": len(exported), "output_dir": str(export_dir), "files": exported}


def _run_render_step(
    layers: List[Dict[str, Any]],
    gis_data: Dict[str, Any],
    output_dir: Any,
    village_name: str,
) -> Dict[str, Any]:
    """Render map layers as PNG using matplotlib."""
    import json as _json

    render_dir = Path(output_dir)
    render_dir.mkdir(parents=True, exist_ok=True)

    # Save GeoJSON layers
    geojson_dir = render_dir / "layers"
    geojson_dir.mkdir(parents=True, exist_ok=True)
    for lyr in layers:
        layer_type = lyr.get("layerType", "unknown")
        geojson = lyr.get("data")
        if geojson and geojson.get("features"):
            filepath = geojson_dir / f"{layer_type}.geojson"
            with open(filepath, "w", encoding="utf-8") as f:
                _json.dump(geojson, f, ensure_ascii=False)

    png_path = render_dir / "layout.png"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        from app.modules.schema import PLANNING_ZONE_COLORS

        fig, ax = plt.subplots(1, 1, figsize=(16, 12))
        ax.set_title(f"{village_name} — layout", fontsize=14)
        ax.set_aspect("equal")

        boundary = gis_data.get("boundary_geojson")
        if boundary and boundary.get("features"):
            _draw_geojson_layer(ax, boundary, edgecolor="#333333", facecolor="none", linewidth=1.5)

        legend_patches = []
        for lyr in layers:
            layer_type = lyr.get("layerType", "unknown")
            geojson = lyr.get("data")
            if not geojson or not geojson.get("features"):
                continue
            if layer_type == "planning_zone":
                for zone_name, color in PLANNING_ZONE_COLORS.items():
                    zone_features = {
                        "type": "FeatureCollection",
                        "features": [f for f in geojson["features"] if f.get("properties", {}).get("zone_type") == zone_name],
                    }
                    if zone_features["features"]:
                        _draw_geojson_layer(ax, zone_features, facecolor=color, alpha=0.6)
                        legend_patches.append(mpatches.Patch(color=color, label=zone_name))
            else:
                _draw_geojson_layer(ax, geojson, facecolor="#AAAAAA", alpha=0.4)

        if legend_patches:
            ax.legend(handles=legend_patches, loc="lower right", fontsize=8)
        ax.autoscale()
        fig.tight_layout()
        fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return {"png_path": str(png_path), "layer_count": len(layers), "render_dir": str(render_dir)}
    except ImportError:
        return {"png_path": None, "note": "matplotlib unavailable", "render_dir": str(render_dir)}
    except Exception as e:
        return {"png_path": None, "error": str(e), "render_dir": str(render_dir)}


def _draw_geojson_layer(
    ax: Any,
    geojson: Dict[str, Any],
    facecolor: str = "#AAAAAA",
    edgecolor: str = "#333333",
    linewidth: float = 0.5,
    alpha: float = 0.5,
):
    """Draw a GeoJSON FeatureCollection on a matplotlib Axes."""
    from shapely.geometry import shape

    for feat in geojson.get("features", []):
        try:
            geom = shape(feat.get("geometry", {}))
            if geom.is_empty:
                continue
            if geom.geom_type == "Polygon":
                xs, ys = geom.exterior.xy
                ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha)
                for interior in geom.interiors:
                    xi, yi = interior.xy
                    ax.fill(xi, yi, facecolor="white", edgecolor="none")
            elif geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    xs, ys = poly.exterior.xy
                    ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha)
                    for interior in poly.interiors:
                        xi, yi = interior.xy
                        ax.fill(xi, yi, facecolor="white", edgecolor="none")
            elif geom.geom_type in ("LineString", "MultiLineString"):
                lines = [geom] if geom.geom_type == "LineString" else geom.geoms
                for line in lines:
                    xs, ys = line.xy
                    ax.plot(xs, ys, color=edgecolor, linewidth=linewidth * 2, alpha=alpha)
            elif geom.geom_type == "Point":
                ax.plot(geom.x, geom.y, "o", color=facecolor, markersize=4, alpha=alpha)
        except Exception:
            continue


def build_three_way_comparison(
    gen_layers: Optional[List[Dict[str, Any]]],
    plan_layers: Optional[List[Dict[str, Any]]],
    planned_data: Dict[str, Any],
    gis_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build three-way comparison report: gen vs planned, plan vs planned, gen vs plan."""
    from app.tools.gis._rendering.compare_layouts import compare

    protection = {}
    for key, name in [
        ("farmland_protection_geojson", "farmland"),
        ("ecological_protection_geojson", "ecological"),
        ("historical_protection_geojson", "historical"),
    ]:
        val = gis_data.get(key)
        if val and val.get("features"):
            protection[name] = val

    comparison: Dict[str, Any] = {}
    if gen_layers and planned_data:
        report = compare(gen_layers, planned_data, protection if protection else None)
        comparison["gen_vs_planned"] = report.to_dict() if hasattr(report, "to_dict") else report
    if plan_layers and planned_data:
        report = compare(plan_layers, planned_data, protection if protection else None)
        comparison["plan_vs_planned"] = report.to_dict() if hasattr(report, "to_dict") else report
    if gen_layers and plan_layers:
        report = compare(gen_layers, plan_layers, protection if protection else None)
        comparison["gen_vs_plan"] = report.to_dict() if hasattr(report, "to_dict") else report

    return comparison
