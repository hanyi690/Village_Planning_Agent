"""Generate standalone HTML map viewer for Jin Tian GIS rendering result."""

import json
import os

outdir = "F:/project/Village_Planning_Agent/output/jintian_render"
os.makedirs(outdir, exist_ok=True)

# First run: generate and export layers
print("Step 1: Generating layers...")
from app.services.modules.gis.layout.data_loader import load_all, resolve_gen_intent
from app.tools.gis.generate import (
    _generate_function_zones,
    _generate_planning_zones,
    _generate_facilities,
    _generate_axes,
)

data = load_all()
intent = resolve_gen_intent("金田村委会", data)

layers = []
for fn, args in [
    (_generate_function_zones, (intent, data)),
    (_generate_planning_zones, (None, data, intent)),
    (_generate_facilities, (intent, data)),
    (_generate_axes, (intent, data)),
]:
    try:
        lyr = fn(*args)
        if lyr:
            layers.append(lyr)
    except Exception as e:
        print(f"  Layer {fn.__name__} failed: {e}")

# Save each layer
for lyr in layers:
    lt = lyr["layerType"]
    fpath = f"{outdir}/{lt}.geojson"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(lyr["data"], f, ensure_ascii=False)
    fc = len(lyr["data"].get("features", []))
    print(f"  Saved {lt}.geojson ({fc} features)")

# Also save boundary
boundary = data.get("boundary_geojson", {})
with open(f"{outdir}/boundary.geojson", "w", encoding="utf-8") as f:
    json.dump(boundary, f, ensure_ascii=False)

# Export 12-layer package
print("Step 2: Exporting 12-layer package...")
from app.tools.gis.export import export_gdb

export_gdb.func(
    layout_configs=layers,
    allocated_geojson=data.get("landuse_current_geojson"),
    gis_data=data,
    village_name="金田村委会",
    output_dir=outdir,
    tool_call_id="render-screenshot",
)

# Read back layers for embedding
print("Step 3: Building HTML...")
layer_data = {}
for name in ["boundary", "function_zone", "planning_zone", "facility_point", "infrastructure"]:
    path = f"{outdir}/{name}.geojson"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            ld = json.load(f)
        # Simplify planning_zone for HTML size
        if name == "planning_zone" and len(ld.get("features", [])) > 100:
            ld = dict(ld)
            ld["features"] = ld["features"][::10]
        layer_data[name] = ld
        print(f"  {name}: {len(ld.get('features',[]))} features")

data_json = json.dumps(layer_data, ensure_ascii=False)

html = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>金田村 GIS 布局渲染结果</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: "Microsoft YaHei", sans-serif; background:#1a1a2e; color:#eee; }
  #map { width:100vw; height:72vh; min-height:500px; }
  #legend { padding:12px 16px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; background:#16213e; }
  .legend-item { display:flex; align-items:center; gap:6px; font-size:13px; white-space:nowrap; }
  .legend-swatch { width:16px; height:16px; border-radius:3px; border:1px solid rgba(255,255,255,0.3); flex-shrink:0; }
  h2 { font-size:16px; margin-right:16px; color:#ffd380; white-space:nowrap; }
  .stats { background:#0f3460; padding:10px 16px; display:flex; gap:24px; flex-wrap:wrap; font-size:12px; color:#aaa; }
  .stats span { color:#ffd380; font-weight:bold; }
</style>
</head>
<body>
<div id="map"></div>
<div id="legend">
  <h2>金田村 空间布局规划 — 渲染结果</h2>
  <div class="legend-item"><div class="legend-swatch" style="background:#68B167"></div>生态绿地 2,230ha</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#F5F8DC"></div>农业用地 100ha</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#FFD380"></div>居住用地 14ha</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#87CEEB"></div>水域 36ha</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#DC143C;border-radius:50%"></div>设施点 46</div>
  <div class="legend-item"><div class="legend-swatch" style="background:#FF0000;width:20px;height:3px;border:none"></div>发展轴</div>
  <div class="legend-item"><div class="legend-swatch" style="background:transparent;border:2px dashed #FFF"></div>村界</div>
</div>
<div class="stats">
  <div>现状地块: <span>660</span></div>
  <div>功能分区: <span>5</span></div>
  <div>设施点: <span>46</span></div>
  <div>总面积: <span>2,353 ha</span></div>
  <div>坐标系: <span>WGS-84 (EPSG:4326)</span></div>
  <div>数据源: <span>data/gis/jintian/</span></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var DATA = __DATA__;

var osmTile = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, opacity: 0.35, attribution: '&copy; OSM'
});

var map = L.map('map', { preferCanvas: true, layers: [osmTile] }).setView([24.819, 116.0415], 14);

// 1. Function zones — main color fill
if (DATA.function_zone && DATA.function_zone.features) {
  L.geoJSON(DATA.function_zone, {
    style: function(f) {
      return {
        color: f.properties.stroke || '#666',
        weight: 1.5,
        fillColor: f.properties.color || '#ccc',
        fillOpacity: 0.55
      };
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      layer.bindTooltip('<b>' + (p.land_use || p.zone_id) + '</b><br/>' +
        '面积: ' + (p.area_ha ? p.area_ha.toFixed(1) : '?') + ' ha', { sticky: true });
    }
  }).addTo(map);
}

// 2. Planning zones — underlay, lighter
if (DATA.planning_zone && DATA.planning_zone.features) {
  L.geoJSON(DATA.planning_zone, {
    style: function(f) {
      return {
        color: f.properties.stroke || f.properties.color || '#888',
        weight: 0.3,
        fillColor: f.properties.color || '#ccc',
        fillOpacity: 0.12
      };
    }
  }).addTo(map);
}

// 3. Facility points
if (DATA.facility_point && DATA.facility_point.features) {
  L.geoJSON(DATA.facility_point, {
    pointToLayer: function(f, latlng) {
      var p = f.properties;
      var color = p.color || '#666';
      var isHazard = (p.facility_type === '地质灾害点');
      var radius = isHazard ? 3.5 : 7;
      return L.circleMarker(latlng, {
        radius: radius,
        fillColor: color,
        color: '#fff',
        weight: 1,
        fillOpacity: 0.9
      });
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      if (p.facility_type && p.facility_type !== '地质灾害点') {
        layer.bindTooltip('<b>' + p.facility_type + '</b> (' + p.status + ')<br/>' +
          '服务覆盖: ' + (p.coverage_count || 0) + ' 户');
      }
    }
  }).addTo(map);
}

// 4. Development axes
if (DATA.infrastructure && DATA.infrastructure.features) {
  L.geoJSON(DATA.infrastructure, {
    style: function(f) {
      if (f.geometry.type === 'Point') return { radius: 8, fillColor: '#FF0000', color: '#fff', weight: 2, fillOpacity: 0.9 };
      return { color: '#FF4444', weight: 3, dashArray: '6,4', opacity: 0.8 };
    },
    pointToLayer: function(f, latlng) {
      return L.circleMarker(latlng, { radius: 9, fillColor: '#FF0000', color: '#FFD700', weight: 2.5, fillOpacity: 0.9 });
    },
    onEachFeature: function(f, layer) {
      var p = f.properties;
      layer.bindTooltip('<b>' + (p.name || p.axis_type || '发展轴') + '</b>');
    }
  }).addTo(map);
}

// 5. Boundary outline (top layer)
if (DATA.boundary && DATA.boundary.features) {
  var bLayer = L.geoJSON(DATA.boundary, {
    style: { color: '#FFFFFF', weight: 2.5, fillOpacity: 0, dashArray: '8,4' }
  }).addTo(map);
  try {
    var bounds = bLayer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
  } catch(e) {}
}
</script>
</body>
</html>
"""

html = html.replace("__DATA__", data_json)

html_path = f"{outdir}/map.html"
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nHTML saved: {html_path}")
print(f"Size: {len(html):,} bytes")
print("\nDone! Open the HTML file in a browser to view the map.")
