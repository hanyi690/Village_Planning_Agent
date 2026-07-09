"""
GIS E2E Visual Test - 直接脚本渲染，不依赖浏览器

1. 调用后端 API 获取 GeoJSON 数据
2. 用 matplotlib + geopandas 渲染为图片
3. 汇总所有测试结果

运行: python scripts/gis_visual_test.py
"""

import json
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from shapely.geometry import shape, Point, mapping
import numpy as np

API_BASE = "http://localhost:8000/api/dev/gis"
OUT_DIR = Path(__file__).parent.parent / "test-screenshots" / "visual"
OUT_DIR.mkdir(parents=True, exist_ok=True)

results = {}

# ============================================
# API helper
# ============================================
def api_call(name, endpoint, method="GET", body=None):
    import urllib.request
    t0 = time.time()
    url = f"{API_BASE}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            timing = int((time.time() - t0) * 1000)
            success = result.get("success", True)
            results[name] = {"success": success, "timing_ms": timing}
            return result
    except Exception as e:
        timing = int((time.time() - t0) * 1000)
        results[name] = {"success": False, "timing_ms": timing, "error": str(e)}
        print(f"  [API] {name}: FAIL {timing}ms - {e}")
        return None

# ============================================
# Plotting helpers
# ============================================
JT_CENTER = [116.044146, 24.818629]

def setup_plot(title, zoom_buffer=0.02):
    fig, ax = plt.subplots(1, 1, figsize=(10, 8), dpi=150)
    ax.set_aspect('equal')
    ax.set_title(title, fontsize=14, fontweight='bold')
    # Default extent around Jintian
    ax.set_xlim(JT_CENTER[0] - zoom_buffer, JT_CENTER[0] + zoom_buffer)
    ax.set_ylim(JT_CENTER[1] - zoom_buffer, JT_CENTER[1] + zoom_buffer)
    return fig, ax

def save_plot(fig, name):
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, bbox_inches='tight', dpi=150)
    plt.close(fig)
    size_kb = os.path.getsize(path) // 1024
    print(f"  Saved: {name}.png ({size_kb}KB)")
    return path

def plot_geojson(ax, geojson, color='blue', alpha=0.5, label=None, edgecolor='black', linewidth=0.5):
    if not geojson or not geojson.get('features'):
        return
    gdf = gpd.GeoDataFrame.from_features(geojson)
    if gdf.empty:
        return
    gdf.plot(ax=ax, color=color, alpha=alpha, edgecolor=edgecolor, linewidth=linewidth, label=label)

def auto_extent(ax, geojson_list, buffer_ratio=0.05):
    all_geoms = []
    for gj in geojson_list:
        if gj and gj.get('features'):
            gdf = gpd.GeoDataFrame.from_features(gj)
            all_geoms.append(gdf.geometry.unary_union)
    if all_geoms:
        combined = gpd.GeoSeries(all_geoms).unary_union
        minx, miny, maxx, maxy = combined.bounds
        dx = (maxx - minx) * buffer_ratio or 0.01
        dy = (maxy - miny) * buffer_ratio or 0.01
        ax.set_xlim(minx - dx, maxx + dx)
        ax.set_ylim(miny - dy, maxy + dy)

# ============================================
# Test: Load jintian boundary as base layer
# ============================================
def load_jintian_boundary():
    boundary = api_call("jintian-boundary", "/jintian/data/boundary_current.geojson")
    return boundary

# ============================================
# Test 1: Status
# ============================================
def test_status():
    print("\n=== Test 1: Service Status ===")
    data = api_call("status", "/status")
    if data and data.get("services"):
        svc = data["services"]
        print(f"  tianditu={svc['tianditu_api_key']} amap={svc['amap_api_key']} "
              f"osmnx={svc['osmnx']} geopandas={svc['geopandas']} jintian={svc['jintian_data']}")
    return data

# ============================================
# Test 2: Data Fetch
# ============================================
def test_data_fetch(boundary_gj):
    print("\n=== Test 2: Data Fetch ===")
    data = api_call("data-fetch", "/data-fetch", "POST", {"location": "金田村委会", "buffer_km": 5})
    if not data or not data.get("success"):
        return

    fig, ax = setup_plot("GIS 数据获取 - 金田村")
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.3, label='边界')
    save_plot(fig, "02-data-fetch")

# ============================================
# Test 3: Center
# ============================================
def test_center(boundary_gj):
    print("\n=== Test 3: Center ===")
    data = api_call("center", "/center", "POST", {"location": "金田村委会"})
    if not data:
        return

    fig, ax = setup_plot("村级中心定位", zoom_buffer=0.03)
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.3, label='边界')

    center = data.get("center")
    if center:
        ax.plot(center[0], center[1], 'r*', markersize=20, label=f'中心 ({center[0]:.4f}, {center[1]:.4f})', zorder=5)
        fallback = data.get("metadata", {}).get("fallback", "")
        if fallback:
            ax.annotate(f'回退: {fallback}', xy=(center[0], center[1]),
                       xytext=(10, 10), textcoords='offset points', fontsize=8, color='red')
    ax.legend(fontsize=8)
    save_plot(fig, "03-center")

# ============================================
# Test 4: Coverage
# ============================================
def test_coverage():
    print("\n=== Test 4: Coverage ===")
    data = api_call("coverage", "/coverage", "POST", {"location": "金田村", "buffer_km": 5})
    if data and data.get("coverage_rate") is not None:
        rate = data["coverage_rate"]
        print(f"  Coverage: {rate * 100:.1f}%")

# ============================================
# Test 5: Isochrone (KEY VISUAL TEST)
# ============================================
def test_isochrone(boundary_gj):
    print("\n=== Test 5: Isochrone (KEY) ===")
    data = api_call("isochrone", "/isochrone", "POST", {
        "center": JT_CENTER,
        "time_minutes": [5, 10, 15],
        "travel_mode": "walk"
    })
    if not data or not data.get("geojson"):
        print("  No isochrone GeoJSON returned")
        return

    geojson = data["geojson"]
    fig, ax = setup_plot("等时圈分析 - 步行可达范围", zoom_buffer=0.02)
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2, label='村界')

    # Plot isochrones with different colors (inner to outer)
    colors = ['#E74C3C', '#F39C12', '#27AE60']
    labels = ['5分钟', '10分钟', '15分钟']
    features = geojson.get("features", [])
    # Sort by area (smallest first = shortest time)
    for i, feat in enumerate(features):
        geom = shape(feat["geometry"])
        color = colors[i % len(colors)]
        label = labels[i % len(labels)]
        gpd.GeoSeries([geom]).plot(ax=ax, color=color, alpha=0.4, edgecolor=color,
                                    linewidth=1.5, label=label)

    # Plot center point
    ax.plot(JT_CENTER[0], JT_CENTER[1], 'k*', markersize=15, label='中心点', zorder=5)

    auto_extent(ax, [boundary_gj, geojson])
    ax.legend(fontsize=9, loc='upper left')
    save_plot(fig, "05-isochrone")

# ============================================
# Test 6: POI Search (KEY VISUAL TEST)
# ============================================
def test_poi_search(boundary_gj):
    print("\n=== Test 6: POI Search (KEY) ===")
    data = api_call("poi-search", "/poi-search", "POST", {
        "keyword": "学校",
        "center": JT_CENTER,
        "radius": 2000
    })
    if not data:
        return

    fig, ax = setup_plot("POI 搜索 - 学校 (2km)", zoom_buffer=0.02)
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2, label='村界')

    # Draw search radius circle
    circle = Point(JT_CENTER).buffer(0.018)  # ~2km approximate
    gpd.GeoSeries([circle]).plot(ax=ax, facecolor='none', edgecolor='blue',
                                  linewidth=1, linestyle='--', label='搜索范围')

    # Plot POIs
    geojson = data.get("geojson")
    total = data.get("total_count", 0)
    if geojson and geojson.get("features"):
        pois_gdf = gpd.GeoDataFrame.from_features(geojson)
        if not pois_gdf.empty:
            pois_gdf.plot(ax=ax, color='red', markersize=30, marker='o',
                          edgecolor='darkred', linewidth=0.5, label=f'学校 ({len(pois_gdf)})', zorder=5)
    else:
        ax.plot(JT_CENTER[0], JT_CENTER[1], 'rx', markersize=10, label='无POI结果')

    ax.plot(JT_CENTER[0], JT_CENTER[1], 'k*', markersize=12, label='搜索中心', zorder=5)
    auto_extent(ax, [boundary_gj])
    ax.legend(fontsize=9, loc='upper left')
    save_plot(fig, "06-poi-search")
    print(f"  POI count: {total}")

# ============================================
# Test 7: Accessibility
# ============================================
def test_accessibility(boundary_gj):
    print("\n=== Test 7: Accessibility ===")
    data = api_call("accessibility", "/accessibility", "POST", {
        "analysis_type": "service_coverage",
        "center": JT_CENTER,
    })
    if not data or not data.get("success"):
        return

    geojson = data.get("geojson")
    if geojson and geojson.get("features"):
        fig, ax = setup_plot("可达性分析 - 服务覆盖")
        if boundary_gj:
            plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2)
        plot_geojson(ax, geojson, color='#8E44AD', alpha=0.4, label='服务覆盖区')
        ax.plot(JT_CENTER[0], JT_CENTER[1], 'k*', markersize=12, zorder=5)
        auto_extent(ax, [boundary_gj, geojson])
        ax.legend(fontsize=9)
        save_plot(fig, "07-accessibility")

# ============================================
# Test 8: Ecological
# ============================================
def test_ecological(boundary_gj):
    print("\n=== Test 8: Ecological ===")
    data = api_call("ecological", "/ecological", "POST", {"use_jintian_data": True})
    if not data or not data.get("success"):
        return

    geojson = data.get("geojson")
    if geojson and geojson.get("features"):
        fig, ax = setup_plot("生态敏感性分析")
        if boundary_gj:
            plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2)
        # Color by sensitivity
        gdf = gpd.GeoDataFrame.from_features(geojson)
        if not gdf.empty and 'sensitivity' in gdf.columns:
            gdf.plot(ax=ax, column='sensitivity', cmap='RdYlGn_r', alpha=0.6,
                    legend=True, legend_kwds={'label': '敏感性等级', 'shrink': 0.6})
        else:
            gdf.plot(ax=ax, color='#27AE60', alpha=0.5, edgecolor='darkgreen', linewidth=0.5)
        auto_extent(ax, [boundary_gj, geojson])
        save_plot(fig, "08-ecological")

# ============================================
# Test 9: Facility Validation
# ============================================
def test_facility_validation(boundary_gj):
    print("\n=== Test 9: Facility Validation ===")
    data = api_call("facility-validation", "/facility-validation", "POST", {
        "facility_type": "公共服务设施",
        "location": JT_CENTER,
    })
    if data and data.get("success"):
        score = data.get("overall_score", "N/A")
        level = data.get("suitability_level", "N/A")
        print(f"  Score: {score}, Level: {level}")

# ============================================
# Test 10: Constraint Validator
# ============================================
def test_constraint_validator():
    print("\n=== Test 10: Constraint Validator ===")
    data = api_call("constraint-validator", "/constraint-validator", "POST", {"strict_mode": False})
    if data:
        print(f"  Valid: {data.get('is_valid')}, Conflicts: {data.get('metric_conflicts')}, Violations: {data.get('constraint_violations')}")

# ============================================
# Test 11: Hazard Buffer (KEY VISUAL TEST)
# ============================================
def test_hazard_buffer(boundary_gj):
    print("\n=== Test 11: Hazard Buffer (KEY) ===")
    data = api_call("hazard-buffer", "/hazard-buffer", "POST", {"buffer_meters": 200})
    if not data or not data.get("geojson"):
        return

    geojson = data["geojson"]
    fig, ax = setup_plot("灾害缓冲区 (200m)")
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2, label='村界')

    gdf = gpd.GeoDataFrame.from_features(geojson)
    if not gdf.empty:
        # Try to color by hazard type
        if 'hazard_type' in gdf.columns:
            for htype, group in gdf.groupby('hazard_type'):
                group.plot(ax=ax, alpha=0.5, label=htype, edgecolor='red', linewidth=0.5)
        else:
            gdf.plot(ax=ax, color='red', alpha=0.4, edgecolor='darkred', linewidth=0.5,
                     label=f'灾害区 ({len(gdf)})')

    auto_extent(ax, [boundary_gj, geojson])
    ax.legend(fontsize=9, loc='upper left')
    save_plot(fig, "11-hazard-buffer")
    print(f"  Hazard features: {len(geojson.get('features', []))}")

# ============================================
# Test 12: Spatial Layout (KEY VISUAL TEST)
# ============================================
def test_spatial_layout(boundary_gj):
    print("\n=== Test 12: Spatial Layout (KEY) ===")
    data = api_call("spatial-layout", "/spatial-layout", "POST", {"village_name": "金田村委会"})
    if not data or not data.get("success"):
        return

    layouts = data.get("layout_configs", [])
    conflicts = data.get("conflicts", {})
    print(f"  Layouts: {len(layouts)}, Conflicts: {conflicts}")

    fig, ax = setup_plot("空间布局生成 - 金田村规划分区", zoom_buffer=0.03)
    if boundary_gj:
        plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2, label='村界')

    # Color map for different zone types
    zone_colors = {
        'residential': '#E74C3C',
        'commercial': '#3498DB',
        'industrial': '#9B59B6',
        'agricultural': '#27AE60',
        'ecological': '#2ECC71',
        'public': '#F39C12',
        'infrastructure': '#1ABC9C',
        'mixed': '#E67E22',
        'conservation': '#16A085',
    }

    all_geojsons = []
    for layout in layouts:
        geojson = layout.get("geojson")
        if not geojson or not geojson.get("features"):
            continue
        all_geojsons.append(geojson)
        gdf = gpd.GeoDataFrame.from_features(geojson)
        if gdf.empty:
            continue

        # Determine zone type for coloring
        zone_type = layout.get("zone_type", layout.get("type", "mixed"))
        color = zone_colors.get(zone_type, '#95A5A6')
        label = layout.get("name", zone_type)
        gdf.plot(ax=ax, color=color, alpha=0.5, edgecolor='black',
                 linewidth=1, label=label)

    if all_geojsons:
        auto_extent(ax, [boundary_gj] + all_geojsons)
    ax.legend(fontsize=8, loc='upper left')
    save_plot(fig, "12-spatial-layout")

# ============================================
# Test 13: Landuse Change
# ============================================
def test_landuse_change(boundary_gj):
    print("\n=== Test 13: Landuse Change ===")
    data = api_call("landuse-change", "/landuse-change", "POST", {"location": "金田村"})
    if not data or not data.get("success"):
        return

    geojson = data.get("geojson")
    current = data.get("current_parcels", 0)
    planned = data.get("planned_parcels", 0)
    print(f"  Current parcels: {current}, Planned parcels: {planned}")

    if geojson:
        fig, axes = plt.subplots(1, 2, figsize=(16, 7), dpi=150)

        # Current
        ax = axes[0]
        ax.set_title("现状用地", fontsize=12, fontweight='bold')
        ax.set_aspect('equal')
        if boundary_gj:
            plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2)
        current_gj = geojson.get("current")
        if current_gj and current_gj.get("features"):
            gdf = gpd.GeoDataFrame.from_features(current_gj)
            if not gdf.empty:
                gdf.plot(ax=ax, cmap='Set3', alpha=0.7, edgecolor='gray', linewidth=0.3)
                auto_extent(ax, [boundary_gj, current_gj])

        # Planned
        ax = axes[1]
        ax.set_title("规划用地", fontsize=12, fontweight='bold')
        ax.set_aspect('equal')
        if boundary_gj:
            plot_geojson(ax, boundary_gj, color='#D4E6F1', alpha=0.2)
        planned_gj = geojson.get("planned")
        if planned_gj and planned_gj.get("features"):
            gdf = gpd.GeoDataFrame.from_features(planned_gj)
            if not gdf.empty:
                gdf.plot(ax=ax, cmap='Set3', alpha=0.7, edgecolor='gray', linewidth=0.3)
                auto_extent(ax, [boundary_gj, planned_gj])

        plt.tight_layout()
        save_plot(fig, "13-landuse-change")

# ============================================
# Main
# ============================================
def main():
    print("=" * 50)
    print("GIS Visual Test - Script Rendering")
    print("=" * 50)

    # Load boundary as base layer
    boundary_gj = load_jintian_boundary()

    # Run all tests
    test_status()
    test_data_fetch(boundary_gj)
    test_center(boundary_gj)
    test_coverage()
    test_isochrone(boundary_gj)
    test_poi_search(boundary_gj)
    test_accessibility(boundary_gj)
    test_ecological(boundary_gj)
    test_facility_validation(boundary_gj)
    test_constraint_validator()
    test_hazard_buffer(boundary_gj)
    test_spatial_layout(boundary_gj)
    test_landuse_change(boundary_gj)

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    passed = sum(1 for r in results.values() if r["success"])
    failed = sum(1 for r in results.values() if not r["success"])
    for name, r in results.items():
        icon = "PASS" if r["success"] else "FAIL"
        err = f" - {r.get('error', '')[:60]}" if r.get("error") else ""
        print(f"  {icon} {name}: {r['timing_ms']}ms{err}")
    print(f"\nAPI: {passed}/{passed + failed} passed")

    # Save results
    with open(OUT_DIR / "test-results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nVisual outputs: {OUT_DIR}")
    print("Done.")

if __name__ == "__main__":
    main()
