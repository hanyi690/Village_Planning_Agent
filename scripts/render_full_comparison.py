#!/usr/bin/env python3
"""
金田村 现状→规划 完整图层对比可视化。

展示多层 GIS 数据叠加效果，参考 docs/gis/jintian_boundary 的完整数据体系:

图层架构:
  L0 底图: 村界 + 地形
  L1 现状: landuse_current (660块, 15种DLBM) + road_current + hazard_points
  L2 规划: landuse_planned (582块, GHYTMC分类) + road_planned + construction_zone
  L3 约束: farmland_protection + ecological_protection + historical_protection
  L4 项目: project_polygons + project_lines + project_points
"""

import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'SimHei'
plt.rcParams['axes.unicode_minus'] = False
import matplotlib.patches as mpatches
import geopandas as gpd
from shapely import from_geojson
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "jintian_boundary")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "output")


def load_gdf(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        gj = json.load(f)
    if not gj.get('features'):
        return None
    geoms = []
    props = []
    for ft in gj['features']:
        g = ft.get('geometry', {})
        if not g or not g.get('coordinates'):
            continue
        geoms.append(from_geojson(json.dumps(g)))
        props.append(ft.get('properties', {}))
    if not geoms:
        return None
    return gpd.GeoDataFrame(props, geometry=geoms, crs='EPSG:4326')


def area_ha(gdf):
    return gdf.to_crs('EPSG:3857').geometry.area.sum() / 10000


def main():
    # ===================================================
    # Load ALL layers
    # ===================================================
    print('Loading GIS layers...')
    boundary = load_gdf('boundary.geojson')
    lu_curr = load_gdf('landuse_current.geojson')
    lu_plan = load_gdf('landuse_planned.geojson')
    road_curr = load_gdf('road_current.geojson')
    road_plan = load_gdf('road_planned.geojson')
    hazard = load_gdf('geological_hazard_points.geojson')
    farmland = load_gdf('farmland_protection.geojson')
    eco = load_gdf('ecological_protection.geojson')
    hist = load_gdf('historical_protection.geojson')
    constr = load_gdf('construction_zone.geojson')
    proj_poly = load_gdf('project_polygons.geojson')
    proj_line = load_gdf('project_lines.geojson')
    proj_pt = load_gdf('project_points.geojson')

    # Project all to EPSG:3857 for display
    def proj(gdf):
        return gdf.to_crs('EPSG:3857') if gdf is not None else None

    boundary_p = proj(boundary)
    lu_curr_p = proj(lu_curr)
    lu_plan_p = proj(lu_plan)
    road_curr_p = proj(road_curr)
    road_plan_p = proj(road_plan)
    hazard_p = proj(hazard)
    farmland_p = proj(farmland)
    eco_p = proj(eco)
    hist_p = proj(hist)
    constr_p = proj(constr)
    proj_poly_p = proj(proj_poly)
    proj_line_p = proj(proj_line)

    # Classify current and planned
    from app.services.modules.gis.layout.zone_generator import resolve_zone_type_for_dlbm

    lu_curr_p['zone_type'] = lu_curr_p['DLBM'].apply(
        lambda x: resolve_zone_type_for_dlbm(str(x).strip()))
    lu_plan_p['zone_type'] = lu_plan_p.apply(
        lambda r: str(r.get('GHYTMC', '')).strip() or '未分类', axis=1)

    # ===================================================
    # Build 2x3 figure
    # ===================================================
    fig, axes = plt.subplots(2, 3, figsize=(30, 20))

    curr_colors = {
        '居住用地': '#FFD700', '产业用地': '#FF6B6B', '公共服务用地': '#4A90D9',
        '生态绿地': '#90EE90', '交通用地': '#808080', '水域': '#87CEEB', '农业用地': '#8B4513',
    }
    plan_colors = {
        '宅基地': '#FFD700', '经营性建设用地': '#FF6B6B', '公共服务设施用地': '#4A90D9',
        '商品林': '#228B22', '生态林': '#006400', '景观与绿化用地': '#90EE90',
        '村内交通用地': '#808080', '对外交通用地': '#A0A0A0', '水域': '#87CEEB',
        '耕地': '#DEB887', '园地': '#8FBC8F', '设施农用地': '#BC8F8F',
        '水利设施用地': '#B0C4DE', '基础设施用地': '#D3D3D3', '其他农用地': '#F5DEB3',
        '未分类': '#DDDDDD',
    }

    bbox = boundary_p.geometry.union_all()

    # ---- Panel 1: 现状用地 (DLBM 分类) ----
    ax = axes[0, 0]
    for zt, c in curr_colors.items():
        sub = lu_curr_p[lu_curr_p['zone_type'] == zt]
        if len(sub) > 0:
            sub.plot(ax=ax, color=c, alpha=0.5, edgecolor='none')
            ax.scatter([], [], color=c, label=f'{zt} ({len(sub)}块)', s=35)
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=1.5)
    ax.set_title(f'现状用地 (三调 DLBM, {len(lu_curr_p)}块, {area_ha(lu_curr_p):.0f}ha)',
                 fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=7, ncol=4)
    ax.axis('off')

    # ---- Panel 2: 规划用地 (GHYTMC 分类) ----
    ax = axes[0, 1]
    for zt, c in plan_colors.items():
        sub = lu_plan_p[lu_plan_p['zone_type'] == zt]
        if len(sub) > 0:
            sub.plot(ax=ax, color=c, alpha=0.55, edgecolor='#444', linewidth=0.2)
            ax.scatter([], [], color=c, label=f'{zt} ({len(sub)}块)', s=35)
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=1.5)
    ax.set_title(f'规划用地 (GHYTMC, {len(lu_plan_p)}块, {area_ha(lu_plan_p):.0f}ha)',
                 fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=6.5, ncol=5)
    ax.axis('off')

    # ---- Panel 3: 变化检测 (Spatial Difference) ----
    ax = axes[0, 2]
    # Classify into simplified categories for change detection
    def simplify_curr(zt):
        m = {'居住用地': '建设用地', '产业用地': '建设用地', '公共服务用地': '建设用地',
             '交通用地': '建设用地', '生态绿地': '生态用地', '农业用地': '农业用地', '水域': '水域'}
        return m.get(zt, '其他')

    def simplify_plan(zt):
        m = {'宅基地': '建设用地', '经营性建设用地': '建设用地', '公共服务设施用地': '建设用地',
             '村内交通用地': '建设用地', '对外交通用地': '建设用地', '基础设施用地': '建设用地',
             '商品林': '生态用地', '生态林': '生态用地', '景观与绿化用地': '生态用地',
             '耕地': '农业用地', '园地': '农业用地', '设施农用地': '农业用地',
             '水利设施用地': '农业用地', '其他农用地': '农业用地', '水域': '水域'}
        return m.get(zt, '其他')

    lu_curr_p['simple'] = lu_curr_p['zone_type'].apply(simplify_curr)
    lu_plan_p['simple'] = lu_plan_p['zone_type'].apply(simplify_plan)

    # Show current as faded base
    for zt, c in {'建设用地': '#808080', '生态用地': '#90EE90', '农业用地': '#DEB887', '水域': '#87CEEB'}.items():
        sub = lu_curr_p[lu_curr_p['simple'] == zt]
        if len(sub) > 0:
            sub.plot(ax=ax, color=c, alpha=0.15, edgecolor='none')

    # Show planned as brighter overlay
    for zt, c in {'建设用地': '#FF4444', '生态用地': '#228B22', '农业用地': '#D2691E', '水域': '#4169E1'}.items():
        sub = lu_plan_p[lu_plan_p['simple'] == zt]
        if len(sub) > 0:
            sub.plot(ax=ax, color=c, alpha=0.5, edgecolor='#333', linewidth=0.3)
            ax.scatter([], [], color=c, label=f'规划{zt} ({len(sub)}块)', s=35)

    boundary_p.boundary.plot(ax=ax, color='black', linewidth=2)
    ax.set_title('变化检测: 现状(淡色) → 规划(浓色)', fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=7.5, ncol=2)
    ax.axis('off')

    # ---- Panel 4: 约束图层 (保护区域) ----
    ax = axes[1, 0]
    lu_curr_p.plot(ax=ax, color='#EEE', alpha=0.3, edgecolor='none')
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=1.5)

    constraints = [
        ('永久基本农田', farmland_p, '#FFE4B5', 0.7),
        ('生态保护红线', eco_p, '#228B22', 0.6),
        ('历史文化保护', hist_p, '#FFA500', 0.7),
        ('建设用地区', constr_p, '#FF6B6B', 0.4),
    ]
    for name, gdf, color, alpha in constraints:
        if gdf is not None and len(gdf) > 0:
            gdf.plot(ax=ax, color=color, alpha=alpha, edgecolor='#555', linewidth=0.4)
            ax.scatter([], [], color=color, label=f'{name} ({len(gdf)}块)', s=35)
    ax.set_title('约束 & 保护区域', fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=7.5, ncol=2)
    ax.axis('off')

    # ---- Panel 5: 道路网络 + 灾害点 ----
    ax = axes[1, 1]
    lu_curr_p.plot(ax=ax, color='#F5F5DC', alpha=0.4, edgecolor='none')
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=1.5)

    if road_curr_p is not None and len(road_curr_p) > 0:
        road_curr_p.plot(ax=ax, color='#4169E1', linewidth=0.8, alpha=0.6, label=f'现状道路 ({len(road_curr_p)}条)')
    if road_plan_p is not None and len(road_plan_p) > 0:
        road_plan_p.plot(ax=ax, color='#FF0000', linewidth=1.2, alpha=0.8, label=f'规划新增道路 ({len(road_plan_p)}条)')
    if hazard_p is not None and len(hazard_p) > 0:
        hazard_p.plot(ax=ax, color='orange', markersize=25, alpha=0.9, marker='^',
                      edgecolor='red', linewidth=0.5, label=f'灾害隐患点 ({len(hazard_p)}处)')

    ax.set_title('交通 & 灾害 (蓝=现状路, 红=规划路, △=灾害点)', fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=7.5, ncol=2)
    ax.axis('off')

    # ---- Panel 6: 建设项目 ----
    ax = axes[1, 2]
    lu_curr_p.plot(ax=ax, color='#F5F5DC', alpha=0.3, edgecolor='none')
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=1.5)

    if proj_poly_p is not None and len(proj_poly_p) > 0:
        proj_poly_p.plot(ax=ax, color='#FF4500', alpha=0.6, edgecolor='#8B0000', linewidth=0.4,
                         label=f'项目用地 ({len(proj_poly_p)}块)')
    if proj_line_p is not None and len(proj_line_p) > 0:
        proj_line_p.plot(ax=ax, color='#FF6347', linewidth=1.5, alpha=0.8,
                         label=f'项目线路 ({len(proj_line_p)}条)')

    ax.set_title('建设项目 (红线=项目用地/线路)', fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=7.5, ncol=2)
    ax.axis('off')

    # ===================================================
    # Layer statistics
    # ===================================================
    stats = [
        f'土地面积: 现状{area_ha(lu_curr_p):.0f}ha → 规划{area_ha(lu_plan_p):.0f}ha (不变)',
        f'规划用途分类: GHYTMC (15类) ≠ 现状 DLBM (15类) — 编码体系不同',
        f'图斑数变化: 660块(现状) → 582块(规划) = 减少78块 (合并/简化)',
    ]
    if farmland_p is not None:
        stats.append(f'基本农田: {area_ha(farmland_p):.0f}ha ({len(farmland_p)}块)')
    if eco_p is not None:
        stats.append(f'生态红线: {area_ha(eco_p):.0f}ha ({len(eco_p)}块)')
    if constr_p is not None:
        stats.append(f'建设用地区: {area_ha(constr_p):.0f}ha ({len(constr_p)}块)')
    if road_curr_p is not None and road_plan_p is not None:
        stats.append(f'道路: {len(road_curr_p)}条(现状) + {len(road_plan_p)}条(规划)')
    if hazard_p is not None:
        stats.append(f'灾害点: {len(hazard_p)}处')
    if proj_poly_p is not None:
        stats.append(f'项目用地: {len(proj_poly_p)}块')

    footer = ' | '.join(stats)
    fig.text(0.5, 0.005, footer, ha='center', fontsize=8, color='#555',
             transform=fig.transFigure, family='SimHei')

    fig.suptitle('金田村 现状→规划 完整 GIS 图层体系 (参考 docs/gis/jintian_boundary)',
                 fontsize=16, fontweight='bold')
    plt.tight_layout(rect=[0, 0.04, 1, 0.97])

    outpath = os.path.join(OUT_DIR, 'map_render.png')
    plt.savefig(outpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'Saved: {outpath}')
    print(f'\nLayer statistics:')
    for s in stats:
        print(f'  {s}')


if __name__ == '__main__':
    main()
