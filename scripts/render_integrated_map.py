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
# 显式注册中文字体（只用单文件 .ttf：SimHei/Noto/Deng 可靠渲染。
# 先移除 fontManager 中的 .ttc（Microsoft YaHei/SimSun 等）——matplotlib Agg
# 渲染 TTC 集合时 face 索引错位，中文字会渲染成豆腐块（方框）。
# bold 文本会 fallback 到 SimHei regular，仍真实渲染，仅有一条无害警告。）
try:
    fm.fontManager.ttflist = [
        f for f in fm.fontManager.ttflist if not f.fname.lower().endswith('.ttc')
    ]
except Exception:
    pass
for _f in ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/NotoSansSC-VF.ttf",
           "C:/Windows/Fonts/Deng.ttf"):
    if os.path.exists(_f):
        try:
            fm.fontManager.addfont(_f)
        except Exception:
            pass
plt.rcParams['font.family'] = 'SimHei'
plt.rcParams['font.sans-serif'] = ['SimHei', 'Noto Sans SC', 'DengXian', 'sans-serif']
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
            "WHERE layer=3 AND content LIKE '%金田村%' "
            "GROUP BY session_id HAVING COUNT(DISTINCT dimension_key) >= 8 "
            "ORDER BY MAX(rowid) DESC LIMIT 1"
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

        # Current typed reports persist JSON claims rather than only legacy
        # markdown tables.  Extract concrete interventions without inventing
        # geometry; locate_projects still requires a real gazetteer match.
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get('claims'), list):
            for claim in payload['claims']:
                if not isinstance(claim, dict):
                    continue
                interventions = claim.get('suggested_interventions') or []
                if isinstance(interventions, str):
                    interventions = [interventions]
                interventions = [
                    str(item).strip() for item in interventions if str(item).strip()
                ]
                location_hints = claim.get('location_hints') or []
                if isinstance(location_hints, str):
                    location_hints = [location_hints]
                location = '、'.join(
                    str(item).strip() for item in location_hints if str(item).strip()
                )
                statement = str(claim.get('statement') or '').strip()
                if not interventions and dk != 'project_bank':
                    continue
                name = interventions[0] if interventions else statement[:40]
                if len(name) < 3 or name in seen:
                    continue
                seen.add(name)
                projects.append({
                    'name': name,
                    'location': location,
                    'scale': (
                        f"{claim.get('quantity')} {claim.get('quantity_unit')}"
                        if claim.get('quantity') is not None else ''
                    ),
                    'source_claim_id': str(claim.get('claim_id') or ''),
                    'source_dimension': dk,
                })

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


def load_gazetteer(village: str = "jintian"):
    """Load the gazetteer as a name/alias -> entry mapping.

    The persisted KG gazetteer is a typed document with an ``entries`` list,
    while older callers used a direct name dictionary.  Normalize both shapes
    here so rendering can place a project only at a real persisted centroid.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "data", "gazetteer", f"{village}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"  [warn] gazetteer load failed: {e}")
        return {}

    if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        entries = [item for item in payload["entries"] if isinstance(item, dict)]
        aliases: dict[str, dict] = {}
        for entry in entries:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            candidates = [name, *(str(x).strip() for x in entry.get("aliases") or [])]
            if "@" in name:
                candidates.append(name.rsplit("@", 1)[1].strip())
            if name.endswith("村"):
                candidates.append(name[:-1])
            for alias in candidates:
                if alias and alias not in aliases:
                    aliases[alias] = entry
        return aliases

    return payload if isinstance(payload, dict) else {}


def locate_projects(projects, gdf_4326, gazetteer):
    """Real project placement: gazetteer centroid only — no hardcoded offsets.

    Projects whose location matches a gazetteer entry get a point at the
    settlement centroid; unmatched projects are returned with located=False
    and rendered as a text list instead of fake points.
    """
    parcel_geometries = {}
    if gdf_4326 is not None and len(gdf_4326) > 0 and "BSM" in gdf_4326.columns:
        parcel_geometries = {
            str(row.BSM): row.geometry
            for row in gdf_4326.itertuples()
            if getattr(row, "BSM", None) and row.geometry is not None and not row.geometry.is_empty
        }

    def _entry_point(entry):
        """Return a real gazetteer/bundle point, never a fabricated offset."""
        bsms = [str(bsm) for bsm in entry.get("bsms") or []]
        geometries = [parcel_geometries[bsm] for bsm in bsms if bsm in parcel_geometries]
        if geometries:
            return gpd.GeoSeries(geometries, crs="EPSG:4326").union_all().centroid
        centroid = entry.get("centroid")
        if isinstance(centroid, (list, tuple)) and len(centroid) >= 2:
            return Point(float(centroid[0]), float(centroid[1]))
        return None

    def _matching_entries(location):
        text = str(location or "")
        keys = sorted((str(key) for key in gazetteer if str(key).strip()), key=len, reverse=True)
        matches = []
        seen_entries = set()
        for key in keys:
            if key not in text:
                continue
            entry = gazetteer[key]
            marker = id(entry)
            if marker in seen_entries:
                continue
            seen_entries.add(marker)
            matches.append(entry)
        return matches

    located = []
    for proj in projects:
        loc = str(proj.get("location") or "")
        name = str(proj.get("name") or "")
        points = [
            point
            for point in (_entry_point(entry) for entry in _matching_entries(loc))
            if point is not None
        ]
        if points:
            representative = gpd.GeoSeries(points, crs="EPSG:4326").union_all().centroid
            located.append({
                "name": name, "location": loc,
                "lon": representative.x, "lat": representative.y,
                "located": True,
                "category": _classify_project(name),
            })
        else:
            located.append({
                "name": name, "location": loc,
                "lon": None, "lat": None,
                "located": False,
                "category": _classify_project(name),
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

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- Load all data ----
    print("\n[1/5] Loading GIS layers...")
    if not SID:
        _latest_session_id()
        print(f"  SID = {SID}")
    boundary = load_gdf('boundary.geojson', CURRENT_DIR)
    lu_curr = load_gdf('landuse.geojson', CURRENT_DIR)
    farmland = load_gdf('farmland_protection.geojson', CURRENT_DIR)
    eco = load_gdf('ecological_protection.geojson', CURRENT_DIR)
    road = load_gdf('road.geojson', CURRENT_DIR)
    hazard = load_gdf('geological_hazard_points.geojson', CURRENT_DIR)
    custom_zones = load_gdf('custom_functional_zone.geojson', OUT_DIR)

    # Project to Web Mercator
    boundary_p = boundary.to_crs('EPSG:3857')
    lu_curr_p = lu_curr.to_crs('EPSG:3857')
    farmland_p = farmland.to_crs('EPSG:3857') if farmland is not None else None
    eco_p = eco.to_crs('EPSG:3857') if eco is not None else None
    road_p = road.to_crs('EPSG:3857') if road is not None else None
    hazard_p = hazard.to_crs('EPSG:3857') if hazard is not None else None

    # ---- 坐标归一化（修复 matplotlib 大坐标 CJK 文本渲染豆腐块 bug）----
    # matplotlib 在 Axes 数据坐标值很大时（如 EPSG:3857 的 ~1.3e7）无法正确渲染
    # 中文字符。把投影坐标整体平移 offset 并缩放到 0-1 单位范围，使数据值落在
    # 极小范围（~0-1），Axes 文本（ax.text/annotate/legend）即可正常渲染中文。
    _bbox_3857 = boundary_p.geometry.union_all().bounds
    _X_OFF = (_bbox_3857[0] + _bbox_3857[2]) / 2.0
    _Y_OFF = (_bbox_3857[1] + _bbox_3857[3]) / 2.0
    _SPAN = max(_bbox_3857[2] - _bbox_3857[0], _bbox_3857[3] - _bbox_3857[1]) or 1.0
    print(f"  coord offset: ({_X_OFF:.0f}, {_Y_OFF:.0f}), span={_SPAN:.0f}")

    def _norm(x, y):
        """真实 3857 坐标 → 归一化 0-1 坐标。"""
        return (x - _X_OFF) / _SPAN, (y - _Y_OFF) / _SPAN

    def _shift(gdf):
        """平移 + 缩放到 0-1 单位坐标（原地）。"""
        if gdf is None or len(gdf) == 0:
            return gdf
        from shapely.affinity import affine_transform

        gdf['geometry'] = gdf.geometry.apply(
            lambda g: affine_transform(
                g, [1.0 / _SPAN, 0, 0, 1.0 / _SPAN, -_X_OFF / _SPAN, -_Y_OFF / _SPAN]
            )
        )
        return gdf

    boundary_p = _shift(boundary_p)
    lu_curr_p = _shift(lu_curr_p)
    if farmland_p is not None:
        farmland_p = _shift(farmland_p)
    if eco_p is not None:
        eco_p = _shift(eco_p)
    if road_p is not None:
        road_p = _shift(road_p)
    if hazard_p is not None:
        hazard_p = _shift(hazard_p)

    from app.data.catalog.advisory_crosswalks import dlbm_to_planning_zone
    lu_curr_p['zone_type'] = lu_curr_p['DLBM'].apply(
        lambda x: dlbm_to_planning_zone(str(x).strip()))

    # ---- Extract projects ----
    print("\n[2/5] Extracting project locations from report...")
    projects = extract_project_locations()
    gazetteer = load_gazetteer()
    located_projects = locate_projects(projects, lu_curr, gazetteer)
    n_located = sum(1 for p in located_projects if p.get("located"))
    print(f"  Located {n_located}/{len(located_projects)} projects via gazetteer")

    # ---- Render map ----
    print("\n[4/5] Rendering integrated map...")
    # The boundary is close to square. A tall poster canvas leaves most of
    # the page empty after GeoPandas enforces equal map aspect, so keep the
    # rendered planning map readable at a single-page review size.
    fig, ax = plt.subplots(1, 1, figsize=(24, 24))

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
        planning_zone_p = _shift(planning_zone_p.to_crs('EPSG:3857'))
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

    # ---- 空间结构标注（structure_overlay.geojson，管线解析 L3 spatial_structure 报告产出） ----
    structure_overlay = load_gdf('structure_overlay.geojson', OUT_DIR)
    if structure_overlay is not None and len(structure_overlay) > 0:
        structure_overlay_p = _shift(structure_overlay.to_crs('EPSG:3857'))
        for _, row in structure_overlay_p.iterrows():
            kind = str(row.get('kind') or 'label')
            label = str(row.get('label') or '')
            color = str(row.get('color') or '#333333')
            geom = row.geometry
            if geom.is_empty or not label:
                continue
            if kind == 'center' and geom.geom_type == 'Point':
                ax.plot(geom.x, geom.y, 'r*', markersize=20, markeredgecolor='darkred',
                        markeredgewidth=2, zorder=10)
                ax.annotate(label, xy=(geom.x, geom.y), fontsize=11, ha='center',
                            va='bottom', fontweight='bold', color='darkred',
                            xytext=(0, 25), textcoords='offset points',
                            bbox=dict(boxstyle='round,pad=0.35', fc='yellow',
                                      alpha=0.9, ec='darkred', lw=1.5))
            elif kind == 'axis' and geom.geom_type == 'LineString':
                gpd.GeoSeries([geom], crs='EPSG:3857').plot(
                    ax=ax, color=color, linewidth=2.5, alpha=0.75, linestyle='-')
                mid = geom.interpolate(0.5, normalized=True)
                ax.annotate(label, xy=(mid.x, mid.y), fontsize=10, ha='center',
                            color=color, fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.25', fc='white',
                                      alpha=0.85, ec=color, lw=1.2))
            else:
                ctr = geom.centroid
                if not ctr.is_empty:
                    ax.annotate(label, xy=(ctr.x, ctr.y), fontsize=11, ha='center',
                                va='center', fontweight='bold', color=color,
                                bbox=dict(boxstyle='round,pad=0.3', fc='white',
                                          alpha=0.85, ec=color, lw=1.2))
        print(f"  structure overlay: {len(structure_overlay_p)} annotations")

    # ---- Custom functional zones (P7 L4 FunctionalZone, vocabulary colors) ----
    custom_legend_items = []
    if custom_zones is not None and len(custom_zones) > 0:
        custom_zones_p = _shift(custom_zones.to_crs('EPSG:3857'))
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

    # ---- Project labels（gazetteer 真实质心；未定位项目只做文本列表） ----
    cat_icons = {
        '公共服务': ('s', '#4A90D9', '□'), '交通': ('D', '#808080', '◇'),
        '市政': ('p', '#228B22', '△'), '产业': ('^', '#FF6B6B', '▲'),
        '文化': ('*', '#FFA500', '★'), '整治': ('o', '#8B4513', '○'),
        '农业': ('P', '#8FBC8F', '⬠'), '其他': ('o', '#666666', '●'),
    }

    labeled_positions = []  # Avoid overlapping labels
    unlocated_projects = []

    for proj in located_projects:
        if not proj.get('located') or proj.get('lon') is None:
            unlocated_projects.append(proj)
            continue
        lon, lat = proj['lon'], proj['lat']
        # 4326 → 3857 for plotting, then normalize to 0-1
        pt = gpd.GeoSeries([Point(lon, lat)], crs='EPSG:4326').to_crs('EPSG:3857')[0]
        x, y = _norm(pt.x, pt.y)
        cat = proj.get('category', '其他')
        marker, color, symbol = cat_icons.get(cat, cat_icons['其他'])

        offset_x, offset_y = 0, 10
        for px, py in labeled_positions:
            dist = np.sqrt((x - px)**2 + (y - py)**2)
            if dist < 300:
                offset_y += 30

        ax.plot(x, y, marker=marker, color=color, markersize=8, alpha=0.9,
                markeredgecolor='white', markeredgewidth=0.5)

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
    # The map geometries were normalized to a 0-1 plot coordinate system;
    # convert metric decoration lengths before adding them to the axes so a
    # 500 m scale bar cannot expand the extent to hundreds of plot units.
    _meters_to_plot = 1.0 / _SPAN

    # North arrow
    bbox = boundary_p.geometry.union_all().bounds
    north_x = bbox[0] + (bbox[2] - bbox[0]) * 0.92
    north_y = bbox[1] + (bbox[3] - bbox[1]) * 0.88
    ax.annotate('N', xy=(north_x, north_y - 200 * _meters_to_plot), fontsize=20, ha='center',
                fontweight='bold')
    ax.annotate(
        '',
        xy=(north_x, north_y + 400 * _meters_to_plot),
        xytext=(north_x, north_y - 400 * _meters_to_plot),
                arrowprops=dict(arrowstyle='->', lw=2, color='black'))

    # Scale bar
    from shapely.geometry import Point as ShpPoint
    scale_x = bbox[0] + (bbox[2] - bbox[0]) * 0.05
    scale_y = bbox[1] + (bbox[3] - bbox[1]) * 0.05
    scale_length_m = 500  # 500m scale bar
    scale_length_plot = scale_length_m * _meters_to_plot
    tick_plot = 30 * _meters_to_plot
    label_offset_plot = 60 * _meters_to_plot
    ax.plot([scale_x, scale_x + scale_length_plot], [scale_y, scale_y],
            'k-', linewidth=3)
    ax.plot([scale_x, scale_x], [scale_y - tick_plot, scale_y + tick_plot], 'k-', linewidth=1.5)
    ax.plot([scale_x + scale_length_plot, scale_x + scale_length_plot],
            [scale_y - tick_plot, scale_y + tick_plot], 'k-', linewidth=1.5)
    ax.text(scale_x + scale_length_plot / 2, scale_y - label_offset_plot, '500m',
            ha='center', fontsize=10, fontweight='bold')

    # ---- 未定位项目文本列表（无 gazetteer 命中的项目，不画假点） ----
    if unlocated_projects:
        list_text = "未落点项目（缺少可核验坐标/地块）：\n" + "\n".join(
            f"· {p['name']}" for p in unlocated_projects[:15]
        )
        ax.text(bbox[0] + (bbox[2] - bbox[0]) * 0.03,
                bbox[1] + (bbox[3] - bbox[1]) * 0.35,
                list_text, fontsize=8, ha='left', va='top',
                bbox=dict(boxstyle='round,pad=0.4', fc='white', alpha=0.9,
                          ec='#999999', lw=0.8))

    # Title — 用 fig.text（figure 分数坐标）而非 ax.set_title，规避
    # matplotlib 大坐标 Axes 文本 CJK 渲染豆腐块 bug
    try:
        from matplotlib.font_manager import FontProperties
        _TITLE_FP = FontProperties(fname='C:/Windows/Fonts/simhei.ttf')
        _TITLE_FP.set_weight('bold')
    except Exception:
        _TITLE_FP = None
    if _TITLE_FP is not None:
        fig.text(0.5, 0.975, '金田村 产业空间布局规划图',
                 fontsize=22, ha='center', va='top', fontproperties=_TITLE_FP)
        fig.text(0.5, 0.935, 'Functional Zones · 三线管控 · 空间结构',
                 fontsize=13, ha='center', va='top', color='#444444',
                 fontproperties=_TITLE_FP)
    else:
        ax.set_title('金田村 产业空间布局规划图\n'
                     'Functional Zones · 三线管控 · 空间结构',
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
              prop=_TITLE_FP,
              title_fontproperties=_TITLE_FP)
    ax.axis('off')

    # Footer
    fig.text(0.5, 0.01,
             f'数据来源: dimension_reports ({SID[:8]}...) + 三调 landuse_current (660块) + boundary (2353ha)  |  '
             '制作工具: Village_Planning_Agent GIS Layout Engine',
             ha='center', fontsize=8, color='#888')

    # ---- Save ----
    print("\n[5/5] Saving...")
    try:
        from matplotlib.font_manager import findfont, FontProperties
        _fp = findfont(FontProperties(family='SimHei', weight='bold'))
        print(f"  [diag] resolved bold font: {os.path.basename(_fp)}")
        print(f"  [diag] ax patches: {len(ax.patches)}, ax texts: {len(ax.texts)}, ax collections: {len(ax.collections)}")
    except Exception as _e:
        print(f"  [diag] font resolve failed: {_e}")
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
