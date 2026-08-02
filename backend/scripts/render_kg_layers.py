"""Visualize KG entities as planar layers using bundle + spatial_ops.

This script validates the KG <-> spatial_ops <-> bundle integration by:
1. Loading jintian data
2. Building KG (L1 entities + L2 relations)
3. Building SpatialIndex (BSM -> geometry bridge)
4. Querying KG for all entity types
5. Resolving BSM -> geometry via SpatialIndex
6. Rendering all layers as a Leaflet HTML map

Output: output/kg_visualization/kg_layers.html
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rdflib import Namespace

from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_spatial_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG

OUTPUT_DIR = "F:/project/Village_Planning_Agent/output/kg_visualization"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PLN = "http://village-planning.org/ontology#"
PLN_NS = Namespace(PLN)

# ── Color palette for land use zones ──

ZONE_COLORS = {
    "生态保护区": "#2d6a4f",
    "生态控制区": "#52b788",
    "农田保护区": "#95d5b2",
    "一般农业区": "#d8f3dc",
    "村庄建设区": "#ffd166",
    "林业发展区": "#74c69d",
}

DLBM_COLORS = {
    "1100": "#95d5b2",  # 耕地 - light green
    "1200": "#b7e4c7",  # 园地
    "1340": "#52b788",  # 商品林
    "1350": "#2d6a4f",  # 生态林 - dark green
    "1400": "#d8f3dc",  # 草地
    "1510": "#d8f3dc",  # 设施农用地
    "2121": "#ffd166",  # 宅基地 - yellow
    "2122": "#ffa45c",  # 公共服务
    "2123": "#f4845f",  # 基础设施
    "2124": "#e85d75",  # 经营性
    "2125": "#a8dadc",  # 景观绿化
    "2126": "#adb5bd",  # 村内交通
    "2200": "#6c757d",  # 对外交通 - gray
    "2270": "#457b9d",  # 水利设施
    "3100": "#4ea8de",  # 水域 - blue
    "3200": "#ced4da",  # 自然保留地 - light gray
}

DEFAULT_COLOR = "#e9ecef"


def get_dlbm_color(dlbm: str) -> str:
    return DLBM_COLORS.get(dlbm, DEFAULT_COLOR)


def _get_centroid(geom: dict) -> list | None:
    """Get centroid [lon, lat] from a GeoJSON geometry dict."""
    try:
        from shapely.geometry import shape
        s = shape(geom)
        if s.is_empty:
            return None
        c = s.centroid
        return [c.x, c.y]
    except Exception:
        return None


def _fix_and_serialize_geom(geom: dict) -> dict | None:
    """Fix invalid geometry with buffer(0), return clean GeoJSON or None."""
    try:
        from shapely.geometry import shape, mapping
        s = shape(geom)
        if s.is_empty:
            return None
        if not s.is_valid:
            s = s.buffer(0)
            if s.is_empty:
                return None
        return mapping(s)
    except Exception:
        return None


# ── Step 1: Load data ──

print("Step 1: Loading jintian data...")
catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")
print(f"  Parcels: {len(bundle.polygons.landuse_current)}")
print(f"  Roads: {len(bundle.lines.roads_current)}")

# ── Step 2: Build spatial relations ──

print("Step 2: Computing parcel relations...")
relations = compute_parcel_relations(
    bundle.polygons.landuse_current,
    roads=bundle.lines.roads_current,
)

# ── Step 3: Build KG ──

print("Step 3: Building KG...")
kg = KGBuilder(village_name="金田村委会").build_from_bundle(
    bundle=bundle,
    parcel_relations=relations,
)
print(f"  Triples: {kg.get_triple_count()}")
print(f"  Parcels: {kg.get_parcel_count()}")

# ── Step 4: Build SpatialIndex ──

print("Step 4: Building SpatialIndex...")
spatial_idx = build_spatial_index(bundle)
if spatial_idx:
    print(f"  SpatialIndex ready")
else:
    print("  WARNING: SpatialIndex not available (geopandas/shapely missing?)")

# ── Step 5: Query KG entities and resolve geometry ──

print("Step 5: Querying KG entities and resolving geometry...")

# Build (bsm, seq) -> geometry lookup from bundle (preserves all features, not just first per BSM)
bundle_geom_lookup = {}
bsm_seq_counter = {}
for p in bundle.polygons.landuse_current:
    bsm = str(getattr(p, "bsm", "")).strip()
    geom = getattr(p, "geometry", None)
    if bsm and geom and isinstance(geom, dict):
        seq = bsm_seq_counter.get(bsm, 0)
        bsm_seq_counter[bsm] = seq + 1
        bundle_geom_lookup[(bsm, seq)] = geom
print(f"  Bundle geometry lookup: {len(bundle_geom_lookup)} entries")

# 5a. Parcels (L1) - query BSM + seq + DLBM + area from KG, resolve geometry from bundle lookup
parcel_features = []
parcel_sparql = f"""
PREFIX pln: <{PLN}>
SELECT ?bsm ?seq ?dlbm ?area ?zone ?vne WHERE {{
  ?p a pln:Parcel ;
     pln:bsm ?bsm .
  OPTIONAL {{ ?p pln:seq ?seq . }}
  OPTIONAL {{ ?p pln:dlbm ?dlbm . }}
  OPTIONAL {{ ?p pln:area_sqm ?area . }}
  OPTIONAL {{ ?p pln:zone_type ?zone . }}
  OPTIONAL {{ ?p pln:vne_code ?vne . }}
}}
"""
parcel_rows = kg.query(parcel_sparql)
print(f"  KG parcels: {len(parcel_rows)}")

for row in parcel_rows:
    bsm = row.get("bsm", "")
    seq = int(row.get("seq", 0))
    dlbm = row.get("dlbm", "")
    zone = row.get("zone", "")
    vne = row.get("vne", "")

    geom = bundle_geom_lookup.get((bsm, seq))
    if not geom:
        continue

    geom = _fix_and_serialize_geom(geom)
    if not geom:
        continue

    color = get_dlbm_color(dlbm)
    parcel_features.append({
        "type": "Feature",
        "geometry": geom,
        "properties": {
            "bsm": bsm,
            "dlbm": dlbm,
            "zone_type": zone,
            "vne_code": vne,
            "color": color,
            "layer_role": "parcel",
        },
    })

print(f"  Resolved parcel geometries: {len(parcel_features)}")

# 5b. Roads (L1)
road_features = []
road_sparql = f"""
PREFIX pln: <{PLN}>
SELECT ?bsm ?level ?name WHERE {{
  ?r a pln:Road .
  OPTIONAL {{ ?r pln:bsm ?bsm . }}
  OPTIONAL {{ ?r pln:road_level ?level . }}
  OPTIONAL {{ ?r pln:name ?name . }}
}}
"""
road_rows = kg.query(road_sparql)
print(f"  KG roads: {len(road_rows)}")

for row in road_rows:
    bsm = row.get("bsm", "")
    name = row.get("name", "")
    level = row.get("level", "")

    geom = None
    if spatial_idx and bsm:
        geom = spatial_idx.get_parcel_geometry(bsm)

    if geom:
        road_features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "bsm": bsm,
                "name": name,
                "road_level": level,
                "color": "#6c757d",
                "layer_role": "road",
            },
        })

# Also get road geometry directly from bundle (fallback)
if not road_features:
    for road in bundle.lines.roads_current:
        bsm = getattr(road, "bsm", "")
        geom = getattr(road, "geometry", None)
        if geom and isinstance(geom, dict):
            road_features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "bsm": bsm,
                    "name": getattr(road, "name", ""),
                    "road_level": getattr(road, "road_level", ""),
                    "color": "#6c757d",
                    "layer_role": "road",
                },
            })
    print(f"  Road geometry from bundle (fallback): {len(road_features)}")

# 5c. Natural settlements (L1) - query name + coordinates from KG
settlement_features = []
settlement_sparql = f"""
PREFIX pln: <{PLN}>
SELECT ?name ?lon ?lat WHERE {{
  ?s a pln:ResidentialCluster .
  OPTIONAL {{ ?s pln:name ?name . }}
  OPTIONAL {{ ?s pln:lon ?lon . }}
  OPTIONAL {{ ?s pln:lat ?lat . }}
}}
"""
settlement_rows = kg.query(settlement_sparql)
print(f"  KG settlements: {len(settlement_rows)}")

for row in settlement_rows:
    name = row.get("name", "")
    lon_str = row.get("lon", "")
    lat_str = row.get("lat", "")
    try:
        lon = float(lon_str) if lon_str else 0.0
        lat = float(lat_str) if lat_str else 0.0
    except (ValueError, TypeError):
        lon, lat = 0.0, 0.0
    settlement_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": name,
            "color": "#e63946",
            "layer_role": "settlement",
        },
    })

# 5d. Adjacency relations (L2) - touches
adjacency_features = []
adj_map = kg.get_adjacency_map()
print(f"  KG adjacency: {len(adj_map)} parcels with neighbors")

# Build adjacency lines (centroid to centroid)
for bsm_a, neighbors in adj_map.items():
    geom_a = spatial_idx.get_parcel_geometry(bsm_a) if spatial_idx else None
    if not geom_a:
        continue
    centroid_a = _get_centroid(geom_a)
    if not centroid_a:
        continue
    for bsm_b in neighbors:
        geom_b = spatial_idx.get_parcel_geometry(bsm_b) if spatial_idx else None
        if not geom_b:
            continue
        centroid_b = _get_centroid(geom_b)
        if not centroid_b:
            continue
        adjacency_features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [centroid_a, centroid_b],
            },
            "properties": {
                "bsm_a": bsm_a,
                "bsm_b": bsm_b,
                "color": "#adb5bd",
                "layer_role": "adjacency",
            },
        })

print(f"  Adjacency (touches) lines: {len(adjacency_features)}")

# 5e2. Nearby relations (L2) - blue thin lines (from KG triples)
nearby_features = []
_nearby_seen = set()
for s, _, o in kg.g.triples((None, PLN_NS.nearby, None)):
    bsm_a = bsm_b = None
    for _, _, lit in kg.g.triples((s, PLN_NS.bsm, None)):
        bsm_a = str(lit)
    for _, _, lit in kg.g.triples((o, PLN_NS.bsm, None)):
        bsm_b = str(lit)
    if not bsm_a or not bsm_b:
        continue
    key = (bsm_a, bsm_b) if bsm_a < bsm_b else (bsm_b, bsm_a)
    if key in _nearby_seen:
        continue
    _nearby_seen.add(key)
    geom_a = spatial_idx.get_parcel_geometry(bsm_a) if spatial_idx else None
    geom_b = spatial_idx.get_parcel_geometry(bsm_b) if spatial_idx else None
    if not geom_a or not geom_b:
        continue
    ca = _get_centroid(geom_a)
    cb = _get_centroid(geom_b)
    if not ca or not cb:
        continue
    dist = None
    for _, _, lit in kg.g.triples((s, PLN_NS.centroid_distance, None)):
        dist = round(float(lit), 1)
    nearby_features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [ca, cb]},
        "properties": {
            "bsm_a": bsm_a,
            "bsm_b": bsm_b,
            "distance_m": dist or 0,
            "color": "#4ea8de",
            "layer_role": "nearby",
        },
    })
print(f"  Nearby lines: {len(nearby_features)}")

# 5e3. Connected via road (L3) - green lines (from KG triples)
connected_features = []
_conn_seen = set()
for s, _, o in kg.g.triples((None, PLN_NS.connected_via_road, None)):
    bsm_a = bsm_b = None
    for _, _, lit in kg.g.triples((s, PLN_NS.bsm, None)):
        bsm_a = str(lit)
    for _, _, lit in kg.g.triples((o, PLN_NS.bsm, None)):
        bsm_b = str(lit)
    if not bsm_a or not bsm_b:
        continue
    key = (bsm_a, bsm_b) if bsm_a < bsm_b else (bsm_b, bsm_a)
    if key in _conn_seen:
        continue
    _conn_seen.add(key)
    geom_a = spatial_idx.get_parcel_geometry(bsm_a) if spatial_idx else None
    geom_b = spatial_idx.get_parcel_geometry(bsm_b) if spatial_idx else None
    if not geom_a or not geom_b:
        continue
    ca = _get_centroid(geom_a)
    cb = _get_centroid(geom_b)
    if not ca or not cb:
        continue
    road_bsm = None
    road_len = None
    for _, _, lit in kg.g.triples((s, PLN_NS.via_road, None)):
        road_bsm = str(lit)
    for _, _, lit in kg.g.triples((s, PLN_NS.road_segment_length, None)):
        road_len = round(float(lit), 1)
    connected_features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [ca, cb]},
        "properties": {
            "bsm_a": bsm_a,
            "bsm_b": bsm_b,
            "road_bsm": road_bsm or "",
            "road_length_m": road_len or 0,
            "color": "#52b788",
            "layer_role": "connected",
        },
    })
print(f"  Connected (via road) lines: {len(connected_features)}")

# 5e. Facilities (L1) - from KG
facility_features = []
facility_sparql = f"""
PREFIX pln: <{PLN}>
SELECT ?name ?type ?lon ?lat WHERE {{
  ?f a pln:Facility .
  OPTIONAL {{ ?f pln:name ?name . }}
  OPTIONAL {{ ?f pln:facility_type ?type . }}
  OPTIONAL {{ ?f pln:lon ?lon . }}
  OPTIONAL {{ ?f pln:lat ?lat . }}
}}
"""
facility_rows = kg.query(facility_sparql)
print(f"  KG facilities: {len(facility_rows)}")

FACILITY_COLORS = {
    "基础设施": "#f4a261",
    "公共服务": "#e9c46a",
}
for row in facility_rows:
    name = row.get("name", "")
    ftype = row.get("type", "")
    lon_str = row.get("lon", "")
    lat_str = row.get("lat", "")
    try:
        lon = float(lon_str) if lon_str else 0.0
        lat = float(lat_str) if lat_str else 0.0
    except (ValueError, TypeError):
        continue
    if lon == 0 and lat == 0:
        continue
    facility_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": name,
            "facility_type": ftype,
            "color": FACILITY_COLORS.get(ftype, "#f4a261"),
            "layer_role": "facility",
        },
    })

# 5f. Village boundary (from bundle.boundary)
boundary_feature = None
boundary = getattr(bundle, "boundary", None)
if boundary:
    bgeom = getattr(boundary, "geometry", None)
    if bgeom:
        bgeom = _fix_and_serialize_geom(bgeom)
    if bgeom:
        boundary_feature = {
            "type": "Feature",
            "geometry": bgeom,
            "properties": {"layer_role": "boundary"},
        }
        print(f"  Boundary: resolved from bundle.boundary")
    else:
        print(f"  Boundary: geometry invalid/unfixable")
else:
    print(f"  Boundary: not found in bundle")

# ── Step 6: Build HTML ──

print("Step 6: Building HTML...")

layers_data = {
    "parcels": {"type": "FeatureCollection", "features": parcel_features},
    "roads": {"type": "FeatureCollection", "features": road_features},
    "settlements": {"type": "FeatureCollection", "features": settlement_features},
    "facilities": {"type": "FeatureCollection", "features": facility_features},
    "adjacency": {"type": "FeatureCollection", "features": adjacency_features},
    "nearby": {"type": "FeatureCollection", "features": nearby_features},
    "connected": {"type": "FeatureCollection", "features": connected_features},
}
if boundary_feature:
    layers_data["boundary"] = {"type": "FeatureCollection", "features": [boundary_feature]}

# Reduce data size: sample relations if too many
if len(nearby_features) > 1000:
    layers_data["nearby"]["features"] = nearby_features[::3]
    print(f"  Sampled nearby to {len(layers_data['nearby']['features'])} for performance")
if len(connected_features) > 500:
    layers_data["connected"]["features"] = connected_features[::2]
    print(f"  Sampled connected to {len(layers_data['connected']['features'])} for performance")

data_json = json.dumps(layers_data, ensure_ascii=False)

html = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>金田村 KG 实体可视化 - L1/L2 图层渲染</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: "Microsoft YaHei", sans-serif; background:#1a1a2e; color:#eee; }
  #map { width:100vw; height:75vh; min-height:500px; }
  #panel { padding:10px 16px; background:#16213e; display:flex; flex-wrap:wrap; gap:12px; align-items:center; }
  .toggle { display:flex; align-items:center; gap:5px; cursor:pointer; font-size:13px; user-select:none; }
  .toggle input { cursor:pointer; }
  .swatch { width:14px; height:14px; border-radius:3px; border:1px solid rgba(255,255,255,0.3); }
  #stats { background:#0f3460; padding:8px 16px; font-size:12px; color:#aaa; display:flex; gap:20px; flex-wrap:wrap; }
  #stats span { color:#ffd380; font-weight:bold; }
  h2 { font-size:15px; color:#ffd380; margin-right:12px; }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h2>KG 图层控制</h2>
  <label class="toggle"><input type="checkbox" id="cb-parcels" checked><div class="swatch" style="background:#95d5b2"></div>地块 (L1)</label>
  <label class="toggle"><input type="checkbox" id="cb-adjacency" checked><div class="swatch" style="background:#adb5bd"></div>邻接 touches (L2)</label>
  <label class="toggle"><input type="checkbox" id="cb-nearby"><div class="swatch" style="background:#4ea8de"></div>近邻 nearby (L2)</label>
  <label class="toggle"><input type="checkbox" id="cb-connected"><div class="swatch" style="background:#52b788"></div>路网连通 (L3)</label>
  <label class="toggle"><input type="checkbox" id="cb-roads" checked><div class="swatch" style="background:#6c757d"></div>道路 (L1)</label>
  <label class="toggle"><input type="checkbox" id="cb-settlements" checked><div class="swatch" style="background:#e63946;border-radius:50%"></div>居民点 (L1)</label>
  <label class="toggle"><input type="checkbox" id="cb-facilities" checked><div class="swatch" style="background:#f4a261;border-radius:50%"></div>设施点 (L1)</label>
  <label class="toggle"><input type="checkbox" id="cb-boundary" checked><div class="swatch" style="background:transparent;border:2px dashed #fff"></div>村界</label>
</div>
<div id="stats">
  <div>KG 三元组: <span>__TRIPLES__</span></div>
  <div>地块: <span>__PARCELS__</span></div>
  <div>道路: <span>__ROADS__</span></div>
  <div>邻接: <span>__ADJ__</span></div>
  <div>近邻: <span>__NEAR__</span></div>
  <div>连通: <span>__CONN__</span></div>
  <div>居民点: <span>__SETTLE__</span></div>
  <div>设施点: <span>__FAC__</span></div>
  <div>坐标系: <span>WGS-84</span></div>
</div>
<div id="legend" style="background:#0f3460;padding:6px 16px;display:flex;flex-wrap:wrap;gap:8px;font-size:12px;">
  <div class="legend-item"><div class="swatch" style="background:#95d5b2"></div>耕地</div>
  <div class="legend-item"><div class="swatch" style="background:#b7e4c7"></div>园地</div>
  <div class="legend-item"><div class="swatch" style="background:#52b788"></div>商品林</div>
  <div class="legend-item"><div class="swatch" style="background:#2d6a4f"></div>生态林</div>
  <div class="legend-item"><div class="swatch" style="background:#d8f3dc"></div>草地/设施农</div>
  <div class="legend-item"><div class="swatch" style="background:#ffd166"></div>宅基地</div>
  <div class="legend-item"><div class="swatch" style="background:#ffa45c"></div>公共服务</div>
  <div class="legend-item"><div class="swatch" style="background:#e85d75"></div>经营性</div>
  <div class="legend-item"><div class="swatch" style="background:#a8dadc"></div>景观绿化</div>
  <div class="legend-item"><div class="swatch" style="background:#adb5bd"></div>村内交通</div>
  <div class="legend-item"><div class="swatch" style="background:#6c757d"></div>对外交通</div>
  <div class="legend-item"><div class="swatch" style="background:#457b9d"></div>水利设施</div>
  <div class="legend-item"><div class="swatch" style="background:#4ea8de"></div>水域</div>
  <div class="legend-item"><div class="swatch" style="background:#ced4da"></div>自然保留地</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var DATA = __DATA__;

var map = L.map('map', { preferCanvas: true }).setView([24.819, 116.0415], 14);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, opacity: 0.15, attribution: '&copy; OSM'
}).addTo(map);

var layers = {};

// Parcels (L1) - colored by DLBM
if (DATA.parcels && DATA.parcels.features) {
  layers.parcels = L.geoJSON(DATA.parcels, {
    style: function(f) {
      return {
        color: '#fff',
        weight: 0.5,
        fillColor: f.properties.color || '#ccc',
        fillOpacity: 0.6
      };
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      layer.bindTooltip(
        '<b>BSM:</b> ' + p.bsm + '<br/>' +
        '<b>地类:</b> ' + (p.dlbm || '?') + '<br/>' +
        '<b>分区:</b> ' + (p.zone_type || '?') + '<br/>' +
        '<b>VNE:</b> ' + (p.vne_code || '?'),
        { sticky: true, className: 'tip' }
      );
    }
  }).addTo(map);
}

// Adjacency (L2) - thin gray lines between touching parcels
if (DATA.adjacency && DATA.adjacency.features) {
  layers.adjacency = L.geoJSON(DATA.adjacency, {
    style: function(f) {
      return {
        color: f.properties.color || '#adb5bd',
        weight: 0.8,
        opacity: 0.5
      };
    }
  }).addTo(map);
}

// Nearby (L2) - blue lines, off by default
if (DATA.nearby && DATA.nearby.features) {
  layers.nearby = L.geoJSON(DATA.nearby, {
    style: function(f) {
      return {
        color: f.properties.color || '#4ea8de',
        weight: 0.5,
        opacity: 0.3
      };
    },
    onEachFeature: function(f, layer) {
      layer.bindTooltip('近邻 ' + f.properties.distance_m + 'm', { sticky: true });
    }
  });
  // Not added to map by default (too many)
}

// Connected via road (L3) - green lines, off by default
if (DATA.connected && DATA.connected.features) {
  layers.connected = L.geoJSON(DATA.connected, {
    style: function(f) {
      return {
        color: f.properties.color || '#52b788',
        weight: 1.5,
        opacity: 0.6
      };
    },
    onEachFeature: function(f, layer) {
      layer.bindTooltip('路网连通 ' + f.properties.road_length_m + 'm', { sticky: true });
    }
  });
}

// Roads (L1)
if (DATA.roads && DATA.roads.features) {
  layers.roads = L.geoJSON(DATA.roads, {
    style: function(f) {
      return {
        color: f.properties.color || '#6c757d',
        weight: 2,
        opacity: 0.8
      };
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      if (p.name) {
        layer.bindTooltip('<b>' + p.name + '</b><br/>' + (p.road_level || ''), { sticky: true });
      }
    }
  }).addTo(map);
}

// Settlements (L1) - red dots
if (DATA.settlements && DATA.settlements.features) {
  layers.settlements = L.geoJSON(DATA.settlements, {
    pointToLayer: function(f, latlng) {
      return L.circleMarker(latlng, {
        radius: 6,
        fillColor: f.properties.color || '#e63946',
        color: '#fff',
        weight: 2,
        fillOpacity: 0.9
      });
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      if (p.name) {
        layer.bindTooltip('<b>' + p.name + '</b>', { sticky: true });
      }
    }
  }).addTo(map);
}

// Facilities (L1) - orange dots
if (DATA.facilities && DATA.facilities.features) {
  layers.facilities = L.geoJSON(DATA.facilities, {
    pointToLayer: function(f, latlng) {
      return L.circleMarker(latlng, {
        radius: 5,
        fillColor: f.properties.color || '#f4a261',
        color: '#fff',
        weight: 1.5,
        fillOpacity: 0.9
      });
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      layer.bindTooltip('<b>' + (p.name || '?') + '</b><br/>' + (p.facility_type || ''), { sticky: true });
    }
  }).addTo(map);
}

// Village boundary - dashed white outline, top layer
if (DATA.boundary && DATA.boundary.features) {
  layers.boundary = L.geoJSON(DATA.boundary, {
    style: {
      color: '#FFFFFF',
      weight: 2.5,
      fillOpacity: 0,
      dashArray: '8,4'
    }
  }).addTo(map);
}

// Layer toggles
function toggleLayer(id, layer) {
  var cb = document.getElementById('cb-' + id);
  if (cb && layer) {
    cb.addEventListener('change', function() {
      if (this.checked) {
        if (!map.hasLayer(layer)) map.addLayer(layer);
      } else {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      }
    });
  }
}
toggleLayer('parcels', layers.parcels);
toggleLayer('adjacency', layers.adjacency);
toggleLayer('nearby', layers.nearby);
toggleLayer('connected', layers.connected);
toggleLayer('roads', layers.roads);
toggleLayer('settlements', layers.settlements);
toggleLayer('facilities', layers.facilities);
toggleLayer('boundary', layers.boundary);

// Fit bounds: prefer boundary, fallback to parcels
var fitTarget = layers.boundary || layers.parcels;
if (fitTarget) {
  try {
    var bounds = fitTarget.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
  } catch(e) {}
}
</script>
</body>
</html>
"""

html = html.replace("__DATA__", data_json)
html = html.replace("__TRIPLES__", str(kg.get_triple_count()))
html = html.replace("__PARCELS__", str(len(parcel_features)))
html = html.replace("__ROADS__", str(len(road_features)))
html = html.replace("__ADJ__", str(len(adjacency_features)))
html = html.replace("__NEAR__", str(len(nearby_features)))
html = html.replace("__CONN__", str(len(connected_features)))
html = html.replace("__SETTLE__", str(len(settlement_features)))
html = html.replace("__FAC__", str(len(facility_features)))

html_path = os.path.join(OUTPUT_DIR, "kg_layers.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nHTML saved: {html_path}")
print(f"Size: {len(html):,} bytes")
print(f"\nLayers rendered:")
print(f"  Parcels (L1):     {len(parcel_features)} features (colored by DLBM)")
print(f"  Roads (L1):       {len(road_features)} features")
print(f"  Settlements (L1): {len(settlement_features)} features")
print(f"  Adjacency (L2):   {len(adjacency_features)} lines (touches)")
print(f"  Nearby (L2):      {len(nearby_features)} lines")
print(f"  Connected (L3):   {len(connected_features)} lines")
print(f"\nOpen in browser to view: file:///{html_path}")
