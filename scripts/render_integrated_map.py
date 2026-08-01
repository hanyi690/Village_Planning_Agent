#!/usr/bin/env python3
"""
Integrated single-page planning map — comparable to CAD output.

Features:
  - Current landuse as faded background
  - Planning zones as colored overlays
  - Spatial structure (一核一带三区) with prominent borders + text
  - Project labels extracted from land_use_planning report
  - North arrow, scale bar, legend
  - Protection zone boundaries
  - Road network overlay
  - High-res PNG output
"""

import json, sys, os, re, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm
plt.rcParams['font.family'] = 'SimHei'
plt.rcParams['axes.unicode_minus'] = False

import geopandas as gpd
from shapely import from_geojson
from shapely.geometry import Point, LineString
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "gis", "jintian")
CURRENT_DIR = os.path.join(DATA_DIR, "current")
PLANNED_DIR = os.path.join(DATA_DIR, "planned")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "output")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "database", "village_planning.db")
SID = ""


def _latest_session_id():
    """Latest session that has L3 reports (dynamic SID, no hardcoding)."""
    global SID
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id, MAX(version) FROM dimension_reports "
            "WHERE layer=3 GROUP BY session_id ORDER BY MAX(version) DESC, MAX(rowid) DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if row:
            SID = row[0]
            return SID
    except Exception as e:
        print(f"  [warn] SID lookup failed: {e}")
    return SID


def load_gdf(filename, subdir=None):
    base = subdir or DATA_DIR
    path = os.path.join(base, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        gj = json.load(f)
    if not gj.get('features'):
        return None
    geoms, props = [], []
    for ft in gj['features']:
        g = ft.get('geometry', {})
        if not g or not g.get('coordinates'):
            continue
        geoms.append(from_geojson(json.dumps(g)))
        props.append(ft.get('properties', {}))
    if not geoms:
        return None
    return gpd.GeoDataFrame(props, geometry=geoms, crs='EPSG:4326')


def extract_project_locations():
    """Extract project names and locations from ALL project-related report tables."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    seen = set()
    projects = []

    # Collect from multiple dimensions
    for dk in ['land_use_planning', 'industry', 'project_bank']:
        cur.execute(
            "SELECT CAST(content AS TEXT) FROM dimension_reports "
            "WHERE session_id=? AND layer=3 AND dimension_key=? "
            "ORDER BY version DESC LIMIT 1", (SID, dk)
        )
        row = cur.fetchone()
        if not row:
            continue
        content = row[0]

        sections = content.split('【')
        for sec in sections:
            # Only process project-related sections
            sec_title = sec.split('】')[0] if '】' in sec else sec[:20]
            if not any(kw in sec_title for kw in ['项目', '建设', '设施', '空间布局']):
                # Also check for project tables
                if '| 项目名称' not in sec and '| 分区' not in sec[:200]:
                    continue

            in_table = False
            for line in sec.split('\n'):
                line = line.strip()
                if '项目名称' in line and '|' in line:
                    in_table = True
                    continue
                if '分区' in line and '产业类型' in line and '|' in line:
                    in_table = True
                    continue
                if in_table and line.startswith('|') and '---' not in line:
                    cells = [c.strip() for c in line.split('|')[1:-1]]
                    if not cells:
                        continue
                    name = cells[0]
                    # Location is always the LAST meaningful column (before timing/status)
                    # Find the column that looks like a location (Chinese place names)
                    location = ''
                    for cell in reversed(cells[1:]):
                        if any(kw in cell for kw in ['村', '段', '域', '线', '路', '园', '坑',
                                                       '前', '竹', '池', '丰', '塘', '水', '头',
                                                       '寨', '心', '区', '耕地', '地', '周边']):
                            location = cell
                            break
                    # Fallback: use the second-to-last or last meaningful column
                    if not location and len(cells) >= 3:
                        location = cells[-2] if len(cells[-1]) < 6 else cells[-1]
                    # Filter non-project rows
                    if any(kw in name for kw in ['项目名称','分区','名称','无','区','公顷','规模',
                                                   '地类','耕地','林地','建设','水域','合计','指标',
                                                   '管控','保护','严禁','限制','集中','盘活','保留',
                                                   '引导','新建','实施','部分','结合','发展','依托',
                                                   '升级','差异化','消除','确保']):
                        continue
                    if len(name) < 4 or len(name) > 40:
                        continue

                    key = name
                    if key not in seen:
                        seen.add(key)
                        projects.append({
                            'name': name,
                            'location': location,
                            'scale': cells[1] if len(cells) >= 2 else '',
                        })
                if in_table and (not line.startswith('|') or line == ''):
                    in_table = False

    conn.close()
    # Deduplicate by name similarity
    deduped = _deduplicate_projects(projects)
    print(f"  Extracted {len(deduped)} unique projects from reports")
    for p in deduped:
        print(f"    {p['name']} @ {p['location']}")
    return deduped


def _deduplicate_projects(projects):
    """Merge similar project names."""
    result = []
    seen_names = set()
    for p in projects:
        name = p['name']
        # Normalize
        norm = name.replace('项目', '').replace('工程', '').replace('建设', '').replace('规划', '')
        if norm in seen_names:
            continue
        seen_names.add(norm)
        result.append(p)
    return result

    print(f"  Extracted {len(projects)} projects from report")
    for p in projects:
        print(f"    {p['name']} @ {p['location']} ({p['area_ha']}ha) [{p['land_type']}]")
    return projects


def geocode_project_locations(projects, boundary_gdf, gdf_4326):
    """Estimate project coordinates from location descriptions."""
    from app.modules.schema import dlbm_to_planning_zone

    # Natural village approximate positions (relative to boundary centroid)
    boundary_ctr = boundary_gdf.to_crs('EPSG:3857').geometry.union_all().centroid

    # Get parcel centroids by DLBM type
    gdf_3857 = gdf_4326.to_crs('EPSG:3857')
    gdf_3857['cx'] = gdf_3857.geometry.centroid.x
    gdf_3857['cy'] = gdf_3857.geometry.centroid.y

    # Village name → offset direction hints
    village_hints = {
        '园寨': (1.0, 1.0),     # center
        '田坑': (0.3, -0.8),     # south
        '社前': (-0.2, -0.5),    # SW
        '分水': (-1.0, 0.3),     # west
        '清明': (-0.8, -0.3),    # SW
        '塘笃': (0.5, -0.5),     # SE
        '长塘': (0.8, 0.0),      # east
        '炉池': (1.2, 1.5),      # NE
        '肩丰': (1.5, 1.0),      # NE
        '营仔': (-0.5, 1.2),     # NW
        '新山': (1.0, 1.3),      # NE
        '黄竹': (-0.3, 1.5),     # NW
        '马头段': (0.5, -0.2),   # SE
    }

    # Build spatial index: village name → centroid
    build_dlbms = {'2121', '2122', '2124', '2125', '2126'}
    build = gdf_3857[gdf_3857['DLBM'].apply(lambda x: str(x).strip() in build_dlbms)]

    located = []

    for proj in projects:
        loc = proj['location']
        name = proj['name']
        x, y = boundary_ctr.x, boundary_ctr.y

        # Try to match village name
        found = False
        for vn, (dx, dy) in village_hints.items():
            if vn in loc:
                # Offset from centroid in direction of village
                spread = 1500  # meters spread
                # Add some random jitter based on project name hash
                seed = sum(ord(c) for c in name)
                jitter_x = (seed % 100 - 50) * 10
                jitter_y = ((seed * 31) % 100 - 50) * 10
                x = boundary_ctr.x + dx * spread + jitter_x
                y = boundary_ctr.y + dy * spread + jitter_y
                found = True
                break

        if not found:
            # Default to spreading around center
            seed = sum(ord(c) for c in name)
            x = boundary_ctr.x + (seed % 300 - 150) * 10
            y = boundary_ctr.y + ((seed * 17) % 300 - 150) * 10

        # Convert back to 4326
        pt_3857 = Point(x, y)
        pt_4326 = gpd.GeoSeries([pt_3857], crs='EPSG:3857').to_crs('EPSG:4326')[0]

        located.append({
            'name': name,
            'lon': pt_4326.x,
            'lat': pt_4326.y,
            'x': x, 'y': y,
            'category': _classify_project(name),
        })

    return located


def _classify_project(name):
    cats = {
        '公共服务': ['服务中心', '广场', '篮球', '卫生', '教育', '学校', '医院', '养老'],
        '交通': ['道路', '路硬', '步道', '停车', '交通', '桥梁', '公交'],
        '市政': ['污水', '给水', '排水', '供水', '垃圾', '公厕', '电力', '通信'],
        '产业': ['加工', '合作社', '产业', '工厂', '种植', '养殖', '田园', '林下', '药苗', '药膳', '美食', '集市', '科普'],
        '文化': ['祠堂', '古树', '古驿', '文化', '民宿', '船灯', '游客'],
        '整治': ['三旧', '改造', '整治', '修复', '危房', '立面'],
        '农业': ['农田', '高标', '水田', '垦造', '灌排'],
    }
    for cat, keywords in cats.items():
        for kw in keywords:
            if kw in name:
                return cat
    return '其他'


def main():
    print("=" * 60)
    print("  Integrated Planning Map Renderer")
    print("=" * 60)

    # ---- Load all data ----
    print("\n[1/5] Loading GIS layers...")
    if not SID:
        _latest_session_id()
        print(f"  SID = {SID}")
    boundary = load_gdf('boundary.geojson', CURRENT_DIR)
    lu_curr = load_gdf('landuse.geojson', CURRENT_DIR)
    farmland = load_gdf('farmland_protection.geojson', PLANNED_DIR)
    eco = load_gdf('ecological_protection.geojson', PLANNED_DIR)
    road = load_gdf('road.geojson', CURRENT_DIR)
    hazard = load_gdf('geological_hazard_points.geojson', PLANNED_DIR)
    custom_zones = load_gdf('custom_functional_zone.geojson', OUT_DIR)

    # Project to Web Mercator
    boundary_p = boundary.to_crs('EPSG:3857')
    lu_curr_p = lu_curr.to_crs('EPSG:3857')
    farmland_p = farmland.to_crs('EPSG:3857') if farmland is not None else None
    eco_p = eco.to_crs('EPSG:3857') if eco is not None else None
    road_p = road.to_crs('EPSG:3857') if road is not None else None
    hazard_p = hazard.to_crs('EPSG:3857') if hazard is not None else None

    from app.modules.schema import dlbm_to_planning_zone
    lu_curr_p['zone_type'] = lu_curr_p['DLBM'].apply(
        lambda x: dlbm_to_planning_zone(str(x).strip()))

    # ---- Extract projects ----
    print("\n[2/5] Extracting project locations from report...")
    projects = extract_project_locations()
    located_projects = geocode_project_locations(projects, boundary, lu_curr)
    print(f"  Located {len(located_projects)} projects")

    # ---- Build spatial structure ----
    print("\n[3/5] Building spatial structure overlay...")
    gdf = lu_curr_p
    gdf['cx'] = gdf.geometry.centroid.x
    gdf['cy'] = gdf.geometry.centroid.y
    cx, cy = gdf['cx'], gdf['cy']
    cx_med, cy_med = cx.median(), cy.median()

    build_dlbms = {'2121', '2122', '2124', '2125'}
    build = gdf[gdf['DLBM'].apply(lambda x: str(x).strip() in build_dlbms)]
    center_mask = (cx > cx.quantile(0.25)) & (cx < cx.quantile(0.75)) & \
                  (cy > cy.quantile(0.25)) & (cy < cy.quantile(0.75))

    structure_zones = {
        '生态保育屏障区': gdf[(cx > cx_med) & (cy > cy_med)],
        '生态农业发展区': gdf[(cx <= cx_med) & (cy <= cy_med)],
        '宜居生活建设区': gdf[center_mask & gdf['DLBM'].apply(
            lambda x: str(x).strip() in build_dlbms)],
    }
    center_pt = build.geometry.union_all().centroid if len(build) > 0 else None

    # ---- Render map ----
    print("\n[4/5] Rendering integrated map...")
    fig, ax = plt.subplots(1, 1, figsize=(24, 30))

    # Background: current landuse by DLBM category (清晰底图，淡化 + 淡描边)
    dlbm_bg = {
        '耕地(11)': ('110', '#f5e6a8', '耕地'),
        '园地(12)': ('120', '#f7d9a8', '园地'),
        '林地(13)': ('130', '#cfe6c4', '林地'),
        '草地(14)': ('140', '#e6f0d9', '草地'),
        '建设用地(21)': ('210', '#e8d5d5', '建设用地'),
        '水域(31)': ('310', '#cfe3f0', '水域'),
    }
    lu_curr_p['dlbm2'] = lu_curr_p['DLBM'].apply(lambda x: str(x)[:3] if str(x) else '')
    for label, (prefix, color, legend) in dlbm_bg.items():
        sub = lu_curr_p[lu_curr_p['dlbm2'] == prefix]
        if len(sub) > 0:
            sub.plot(ax=ax, color=color, alpha=0.55, edgecolor='#ffffff', linewidth=0.2)
    other = lu_curr_p[~lu_curr_p['dlbm2'].isin([p for p, _, _ in dlbm_bg.values()])]
    if len(other) > 0:
        other.plot(ax=ax, color='#f0f0f0', alpha=0.5, edgecolor='#ffffff', linewidth=0.2)

    # Farmland protection: beige outline
    if farmland_p is not None:
        farmland_p.boundary.plot(ax=ax, color='#8B4513', linewidth=1.2, alpha=0.6,
                                 linestyle='--', label='永久基本农田')

    # Ecological protection: green outline
    if eco_p is not None:
        eco_p.boundary.plot(ax=ax, color='#006400', linewidth=1.5, alpha=0.7,
                            linestyle='-.', label='生态保护红线')

    # Roads
    if road_p is not None:
        road_p.plot(ax=ax, color='#4169E1', linewidth=0.8, alpha=0.5, label='现状道路')

    # ---- 规划分区层（planning_zone，若已落盘） ----
    planning_zone_legend = []
    planning_zone_p = load_gdf('planning_zone.geojson', OUT_DIR)
    if planning_zone_p is not None and len(planning_zone_p) > 0:
        planning_zone_p = planning_zone_p.to_crs('EPSG:3857')
        for _, row in planning_zone_p.iterrows():
            color = str(row.get('color') or '#CCCCCC')
            zt = str(row.get('zone_type') or row.get('assigned_zone') or '分区')
            if row.geometry.is_empty:
                continue
            gpd.GeoSeries([row.geometry], crs='EPSG:3857').plot(
                ax=ax, color=color, alpha=0.25, edgecolor=color, linewidth=0.8)
            if zt not in [x[0] for x in planning_zone_legend]:
                planning_zone_legend.append((zt, color))
        print(f"  planning_zone overlay: {len(planning_zone_legend)} zone types")

    # ---- Spatial structure: 只保留一核一带标注，移除大色块填充（原"看不懂"元凶） ----
    struct_colors = {
        '生态保育屏障区': ('#2E8B57', '生态保育\n屏障区\n362ha'),
        '生态农业发展区': ('#DEB887', '生态农业\n发展区\n1961ha'),
        '宜居生活建设区': ('#FF6347', '宜居生活\n建设区\n31ha'),
    }
    for name, (color, label) in struct_colors.items():
        if name in structure_zones and len(structure_zones[name]) > 0:
            parcels = structure_zones[name]
            # 只画虚线边界 + 标签（不再填充大色块 — 避免盖住底图/分区）
            boundary_geom = parcels.geometry.union_all()
            if not boundary_geom.is_empty:
                simplified = boundary_geom.simplify(100, preserve_topology=True)
                gpd.GeoSeries([simplified], crs='EPSG:3857').boundary.plot(
                    ax=ax, color=color, linewidth=1.8, linestyle='--', alpha=0.7)

                # Text label at zone centroid
                ctr = simplified.centroid
                ax.annotate(label, xy=(ctr.x, ctr.y), fontsize=10, ha='center',
                            va='center', fontweight='bold', color=color,
                            bbox=dict(boxstyle='round,pad=0.3', fc='white',
                                      alpha=0.85, ec=color, lw=1.2))

    # ---- Custom functional zones (P7 L4 FunctionalZone, vocabulary colors) ----
    custom_legend_items = []
    if custom_zones is not None and len(custom_zones) > 0:
        custom_zones_p = custom_zones.to_crs('EPSG:3857')
        for _, row in custom_zones_p.iterrows():
            color = str(row.get('color') or '#CCCCCC')
            name = str(row.get('category_name_zh') or row.get('category_code') or '功能区')
            geom = row.geometry
            if geom.is_empty:
                continue
            gpd.GeoSeries([geom], crs='EPSG:3857').plot(
                ax=ax, color=color, alpha=0.45, edgecolor=color, linewidth=1.5)
            ctr = geom.centroid
            if not ctr.is_empty:
                ax.annotate(name, xy=(ctr.x, ctr.y), fontsize=10, ha='center', va='center',
                            fontweight='bold', color='black',
                            bbox=dict(boxstyle='round,pad=0.25', fc='white',
                                      alpha=0.9, ec=color, lw=1.5))
            custom_legend_items.append((name, color))

    # 一核 marker
    if center_pt is not None:
        ax.plot(center_pt.x, center_pt.y, 'r*', markersize=25, markeredgecolor='darkred',
                markeredgewidth=2, zorder=10)
        ax.annotate('一核\n村级综合\n服务中心', xy=(center_pt.x, center_pt.y),
                    fontsize=12, ha='center', va='bottom', fontweight='bold',
                    color='darkred', xytext=(0, 30), textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.4', fc='yellow', alpha=0.9,
                              ec='darkred', lw=1.5),
                    arrowprops=dict(arrowstyle='->', color='darkred', lw=2))

    # 一带 (water corridor)
    water = gdf[gdf['DLBM'].apply(lambda x: str(x).strip() == '3100')]
    if len(water) >= 3:
        wctrs = sorted([g.centroid for g in water.geometry if not g.is_empty],
                       key=lambda p: (p.y, p.x))
        if len(wctrs) >= 2:
            coords = [(p.x, p.y) for p in wctrs][::max(1, len(wctrs)//6)]
            if len(coords) >= 2:
                line = LineString(coords)
                gpd.GeoSeries([line], crs='EPSG:3857').plot(
                    ax=ax, color='#0066CC', linewidth=3, alpha=0.8, linestyle='-')
                mid_pt = line.interpolate(0.5, normalized=True)
                ax.annotate('一带: 金田河\n生态景观带\n(西南→东北)',
                            xy=(mid_pt.x, mid_pt.y), fontsize=10, ha='center',
                            color='#0066CC', fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', fc='lightblue',
                                      alpha=0.85, ec='#0066CC', lw=1.2))

    # ---- Project labels ----
    cat_icons = {
        '公共服务': ('s', '#4A90D9', '□'), '交通': ('D', '#808080', '◇'),
        '市政': ('p', '#228B22', '△'), '产业': ('^', '#FF6B6B', '▲'),
        '文化': ('*', '#FFA500', '★'), '整治': ('o', '#8B4513', '○'),
        '农业': ('P', '#8FBC8F', '⬠'), '其他': ('o', '#666666', '●'),
    }

    # Use text labels for projects (like CAD)
    labeled_positions = []  # Avoid overlapping labels

    for i, proj in enumerate(located_projects):
        x = proj['x']
        y = proj['y']
        cat = proj.get('category', '其他')
        marker, color, symbol = cat_icons.get(cat, cat_icons['其他'])

        # Avoid label overlap: offset if too close to another label
        offset_x, offset_y = 0, 10
        for px, py in labeled_positions:
            dist = np.sqrt((x - px)**2 + (y - py)**2)
            if dist < 300:
                offset_y += 30

        ax.plot(x, y, marker=marker, color=color, markersize=8, alpha=0.9,
                markeredgecolor='white', markeredgewidth=0.5)

        # Text label
        ax.annotate(proj['name'], xy=(x, y), fontsize=7, ha='center', va='bottom',
                    color=color, fontweight='bold', xytext=(offset_x, offset_y),
                    textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.85,
                              ec=color, lw=0.5))

        labeled_positions.append((x, y))

    # ---- Hazard points ----
    if hazard_p is not None:
        hazard_p.plot(ax=ax, color='orange', markersize=6, marker='x',
                      alpha=0.6, linewidth=0.8, label='灾害隐患点')

    # Boundary (outermost, thick black line)
    boundary_p.boundary.plot(ax=ax, color='black', linewidth=2.5, label='村行政边界')

    # ---- Map decorations ----
    # North arrow
    bbox = boundary_p.geometry.union_all().bounds
    north_x = bbox[0] + (bbox[2] - bbox[0]) * 0.92
    north_y = bbox[1] + (bbox[3] - bbox[1]) * 0.88
    ax.annotate('N', xy=(north_x, north_y - 200), fontsize=20, ha='center',
                fontweight='bold')
    ax.annotate('', xy=(north_x, north_y + 400), xytext=(north_x, north_y - 400),
                arrowprops=dict(arrowstyle='->', lw=2, color='black'))

    # Scale bar
    from shapely.geometry import Point as ShpPoint
    scale_x = bbox[0] + (bbox[2] - bbox[0]) * 0.05
    scale_y = bbox[1] + (bbox[3] - bbox[1]) * 0.05
    scale_length_m = 500  # 500m scale bar
    ax.plot([scale_x, scale_x + scale_length_m], [scale_y, scale_y],
            'k-', linewidth=3)
    ax.plot([scale_x, scale_x], [scale_y - 30, scale_y + 30], 'k-', linewidth=1.5)
    ax.plot([scale_x + scale_length_m, scale_x + scale_length_m],
            [scale_y - 30, scale_y + 30], 'k-', linewidth=1.5)
    ax.text(scale_x + scale_length_m / 2, scale_y - 60, '500m',
            ha='center', fontsize=10, fontweight='bold')

    # Title
    ax.set_title('金田村 产业空间布局规划图\n'
                 'Custom Functional Zones · 一核引领 · 一带串联 · 三区协同',
                 fontsize=18, fontweight='bold', pad=20)

    # Legend
    legend_items = [
        ('永久基本农田', '#8B4513', '--'),
        ('生态保护红线', '#006400', '-.'),
        ('现状道路', '#4169E1', '-'),
    ]
    for _, color, ls in legend_items:
        pass  # Using custom legend below

    custom_lines = [
        # 底图组
        mpatches.Patch(color='#f5e6a8', alpha=0.55, label='底图-耕地'),
        mpatches.Patch(color='#cfe6c4', alpha=0.55, label='底图-林地'),
        mpatches.Patch(color='#e8d5d5', alpha=0.55, label='底图-建设用地'),
        mpatches.Patch(color='#cfe3f0', alpha=0.55, label='底图-水域'),
        # 控制线组
        mpatches.Patch(color='#FFE4B5', alpha=0.5, label='永久基本农田'),
        mpatches.Patch(color='#228B22', alpha=0.4, label='生态保护红线'),
        plt.Line2D([0], [0], color='#4169E1', linewidth=1, label='现状道路'),
    ]
    for zt, color in planning_zone_legend:
        custom_lines.append(mpatches.Patch(color=color, alpha=0.25, label=f'规划分区-{zt}'))
    for name, color in custom_legend_items:
        custom_lines.append(mpatches.Patch(color=color, alpha=0.45, label=f'功能区-{name}'))
    for cat, (marker, color, _) in cat_icons.items():
        if any(p.get('category') == cat for p in located_projects):
            custom_lines.append(
                plt.Line2D([0], [0], marker=marker, color=color, markersize=8,
                           linestyle='None', label=f'{cat}项目')
            )

    ax.legend(handles=custom_lines, loc='upper left', fontsize=8,
              ncol=2, framealpha=0.9, title='图例',
              title_fontproperties={'size': 10, 'weight': 'bold'})

    ax.axis('off')

    # Footer
    fig.text(0.5, 0.01,
             '数据来源: dimension_reports (dc2a2e0e v14) + 三调 landuse_current (660块) + boundary (2353ha)  |  '
             '制作工具: Village_Planning_Agent GIS Layout Engine',
             ha='center', fontsize=8, color='#888')

    # ---- Save ----
    print("\n[5/5] Saving...")
    outpath = os.path.join(OUT_DIR, 'integrated_planning_map.png')
    plt.savefig(outpath, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {outpath}")
    print(f"\nMap features:")
    print(f"  Landuse parcels: {len(lu_curr_p)} (background)")
    print(f"  Protection zones: {len(farmland_p) if farmland_p is not None else 0} farmland + {len(eco_p) if eco_p is not None else 0} ecological")
    print(f"  Roads: {len(road_p) if road_p is not None else 0}")
    print(f"  Spatial structure: 3 zones + 1 center + 1 corridor")
    print(f"  Project labels: {len(located_projects)}")
    print(f"  Hazard points: {len(hazard_p) if hazard_p is not None else 0}")
    print(f"  Decorations: north arrow + scale bar + legend")
    print(f"\nDone! Compare with: docs/gis/jintian_dxf/project_layout_clean.svg")


if __name__ == '__main__':
    main()
