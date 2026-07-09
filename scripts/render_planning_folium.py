#!/usr/bin/env python3
"""
Render ALL 6 GISLayerConfig layers including development_axis as visible overlays.
Uses the complete output_gis_layer_configs.json pipeline output.
"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import folium
from folium.plugins import Fullscreen

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "jintian_boundary")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "gis", "output")

# Load pipeline output
with open(os.path.join(OUT_DIR, "output_gis_layer_configs.json")) as f:
    configs = json.load(f)

# Map center
with open(os.path.join(DATA_DIR, "boundary.geojson")) as f:
    boundary = json.load(f)
ring = boundary['features'][0]['geometry']['coordinates'][0][0]
mid = ring[len(ring)//2]

m = folium.Map(location=[mid[1], mid[0]], zoom_start=13, control_scale=True)

# Base map tiles
folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)
folium.TileLayer(
    tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    attr='CartoDB', name='CartoDB 浅色').add_to(m)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri', name='ESRI 卫星').add_to(m)

# Render each layer type with appropriate styling
dev_axis_features = []

for cfg in configs:
    lt = cfg['layerType']
    ln = cfg['layerName']
    gj = cfg['geojson']

    if lt == 'boundary':
        folium.GeoJson(gj, name='村行政边界', show=True,
            style_function=lambda x: {'color': '#333', 'weight': 2.5, 'fillOpacity': 0,
                                      'dashArray': '6,3'}).add_to(m)

    elif lt == 'sensitivity_zone':
        def sens_style(feat):
            pt = feat['properties'].get('protection_type', 'farmland')
            c = {'farmland': '#FFE4B5', 'ecological': '#228B22', 'historical': '#FFA500'}.get(pt, '#CCC')
            return {'color': c, 'weight': 0.5, 'fillColor': c, 'fillOpacity': 0.4}
        folium.GeoJson(gj, name='保护区域 (基本农田+生态+历史)', show=False,
            style_function=sens_style).add_to(m)

    elif lt == 'function_zone':
        def fz_style(feat):
            c = feat['properties'].get('color', '#CCC')
            return {'color': '#444', 'weight': 0.5, 'fillColor': c, 'fillOpacity': 0.45}
        folium.GeoJson(gj, name='功能分区', show=True,
            style_function=fz_style,
            tooltip=folium.GeoJsonTooltip(
                fields=['land_use', 'area_ha', 'DLBM', 'DLMC'],
                aliases=['类型', '面积(ha)', 'DLBM', '地类'])).add_to(m)

    elif lt == 'planning_zone':
        def pz_style(feat):
            c = feat['properties'].get('color', '#CCC')
            changed = feat['properties'].get('changed', False)
            weight = 1.5 if changed else 0.3
            return {'color': c, 'weight': weight, 'fillColor': c, 'fillOpacity': 0.5}
        folium.GeoJson(gj, name='规划分区 (4区, KG约束驱动)', show=True,
            style_function=pz_style,
            tooltip=folium.GeoJsonTooltip(
                fields=['assigned_zone', 'area_ha', 'changed', 'original_zone'],
                aliases=['规划分区', '面积(ha)', '已变更', '现状分类'])).add_to(m)

    elif lt == 'development_axis':
        # Save for special rendering below
        dev_axis_features = gj.get('features', [])

    elif lt == 'infrastructure':
        def infra_style(feat):
            it = feat['properties'].get('infra_type', 'road')
            return {'color': '#4169E1', 'weight': 1.2} if it == 'road' else \
                   {'color': '#FF6347', 'weight': 0.5, 'fillColor': '#FF6347', 'fillOpacity': 0.25}
        folium.GeoJson(gj, name='基础设施 (道路+建设区)', show=False,
            style_function=infra_style).add_to(m)

    elif lt == 'facility_point':
        folium.GeoJson(gj, name='灾害隐患点 (40处)', show=False,
            marker=folium.CircleMarker(radius=4, color='orange', fill=True, fillColor='red', fillOpacity=0.7),
            tooltip=folium.GeoJsonTooltip(
                fields=['地质灾害点名称', '类型'], aliases=['名称', '类型'])).add_to(m)

# === Render development_axis as PROMINENT layers ===
if dev_axis_features:
    for feat in dev_axis_features:
        geom = feat.get('geometry', {})
        props = feat.get('properties', {})
        gtype = geom.get('type', '')
        name = props.get('name', '')
        desc = props.get('description', '')

        if gtype == 'Point':
            coords = geom.get('coordinates', [])
            if len(coords) >= 2:
                folium.Marker(
                    location=[coords[1], coords[0]],
                    popup=folium.Popup(f'<b>{name}</b><br>{desc}', max_width=300),
                    icon=folium.Icon(color='darkred', icon='star', prefix='fa'),
                    name=f'空间结构: {name}'
                ).add_to(m)

        elif gtype == 'LineString':
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': [feat]},
                name=f'空间结构: {name}',
                show=True,
                style_function=lambda x: {'color': '#0066CC', 'weight': 3.5, 'opacity': 0.9},
                tooltip=folium.GeoJsonTooltip(
                    fields=['name', 'description'], aliases=['名称', '说明'])
            ).add_to(m)

        elif gtype in ('Polygon', 'MultiPolygon'):
            zone_colors = {
                '生态保育屏障区': '#2E8B57',
                '生态农业发展区': '#DEB887',
                '宜居生活建设区': '#FF6347',
            }
            c = zone_colors.get(name, '#CCCCCC')
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': [feat]},
                name=f'空间结构: {name}',
                show=True,
                style_function=lambda x, c=c: {
                    'color': c, 'weight': 2.5, 'fillColor': c, 'fillOpacity': 0.15,
                    'dashArray': '8,4'
                },
                highlight_function=lambda x: {'color': '#000', 'weight': 4, 'fillOpacity': 0.3},
                tooltip=folium.GeoJsonTooltip(
                    fields=['name', 'area_ha', 'description'],
                    aliases=['分区', '面积(ha)', '说明'])
            ).add_to(m)

# Legend
legend = (
    '<div style="position:fixed;bottom:30px;right:20px;background:rgba(255,255,255,0.95);'
    'padding:14px;border-radius:8px;box-shadow:0 3px 10px rgba(0,0,0,0.3);font-size:13px;z-index:9999;">'
    '<b style="font-size:15px;">金田村 规划全图层</b><br>'
    '<span style="font-size:10px;color:#888;">6层数据: 边界 + 功能区 + 空间结构 + 保护区 + 基础设施 + 灾害点</span>'
    '<hr style="margin:6px 0;">'
    '⭐ <b>一核</b> 村级服务中心 (园寨)<br>'
    '<span style="color:#0066CC;font-size:16px;">━━</span> <b>一带</b> 金田河生态景观带<br>'
    '<span style="color:#2E8B57;font-size:16px;">╌╌╌</span> <b>生态保育屏障区</b> (NE)<br>'
    '<span style="color:#DEB887;font-size:16px;">╌╌╌</span> <b>生态农业发展区</b> (SW)<br>'
    '<span style="color:#FF6347;font-size:16px;">╌╌╌</span> <b>宜居生活建设区</b> (Center)<br>'
    '<hr style="margin:6px 0;">'
    '使用右上角 <b>图层控件</b> 切换显示<br>'
    '</div>'
)
m.get_root().html.add_child(folium.Element(legend))

folium.LayerControl(collapsed=False).add_to(m)
Fullscreen().add_to(m)

outpath = os.path.join(OUT_DIR, 'jintian_function_zone.html')
m.save(outpath)
print(f'Saved: {outpath}')
print(f'Layers: {len(configs)} config types')
for cfg in configs:
    nf = len(cfg['geojson']['features'])
    print(f'  {cfg["layerType"]}: {cfg["layerName"]} ({nf} features)')
print(f'  development_axis: 5 features rendered as Point + LineString + 3× Polygon')
