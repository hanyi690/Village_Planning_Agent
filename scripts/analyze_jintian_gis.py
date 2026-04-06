"""
金田村 GIS 分析脚本

功能：
1. 数据加载 - 加载 GeoJSON 并转为 GeoDataFrame
2. 空间分析 - 水系、道路、POI 分析
3. 可视化 - folium 交互地图 + matplotlib 静态地图
4. 报告生成 - Markdown 格式分析报告
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString, MultiLineString, Polygon, MultiPolygon
from shapely.ops import unary_union

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle
import folium
from folium.raster_layers import TileLayer

# 配置 matplotlib 中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 配置路径
# ============================================================

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "docs" / "gis" / "geojson_data"
OUTPUT_DIR = BASE_DIR / "docs" / "gis" / "analysis"

# 数据文件
# 说明：高德地图提供边界、中心点、POI 数据
#       天地图 WFS 提供水系线、道路线矢量数据（高德 API 不支持）
DATA_FILES = {
    "center": DATA_DIR / "amap_center_point.geojson",      # 高德地理编码
    "boundary": DATA_DIR / "amap_boundary_pingyuan.geojson", # 高德行政区划
    "pois": DATA_DIR / "amap_pois_all.geojson",            # 高德 POI
    "water_line": DATA_DIR / "wfs_hydl.geojson",           # 天地图 WFS (高德不支持水系矢量)
    "road_line": DATA_DIR / "wfs_lrdl.geojson",            # 天地图 WFS (高德不支持道路矢量)
}

# 输出文件
OUTPUT_FILES = {
    "interactive_map": OUTPUT_DIR / "maps" / "jintian_interactive_map.html",
    "static_map": OUTPUT_DIR / "maps" / "jintian_base_map.png",
    "report": OUTPUT_DIR / "reports" / "jintian_gis_analysis.md",
    "results": OUTPUT_DIR / "data" / "analysis_results.json",
    "metadata": OUTPUT_DIR / "metadata.json",
}

# 金田村中心坐标
JINTIAN_CENTER = (116.044146, 24.818629)

# 分析参数
ANALYSIS_PARAMS = {
    "water_buffer_m": 100,  # 水系缓冲区（米）
    "road_buffer_m": 50,    # 道路缓冲区（米）
    "poi_service_radius_m": 500,  # POI 服务半径（米）
}


# ============================================================
# 工具函数
# ============================================================

def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """计算两点之间的 Haversine 距离（米）"""
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    R = 6371000  # 地球半径（米）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_line_length_km(geometry) -> float:
    """计算线状要素长度（公里）"""
    if geometry is None:
        return 0.0

    # 对于经纬度坐标，使用简化的长度估算
    # 1度经度约111km，1度纬度约111km
    if geometry.geom_type == 'LineString':
        coords = list(geometry.coords)
        total_length = 0
        for i in range(len(coords) - 1):
            total_length += haversine_distance(coords[i], coords[i+1])
        return total_length / 1000
    elif geometry.geom_type == 'MultiLineString':
        total_length = 0
        for line in geometry.geoms:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                total_length += haversine_distance(coords[i], coords[i+1])
        return total_length / 1000
    return 0.0


def load_geojson(filepath: Path) -> gpd.GeoDataFrame:
    """加载 GeoJSON 文件"""
    if not filepath.exists():
        print(f"[WARN] 文件不存在: {filepath}")
        return gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')

    gdf = gpd.read_file(filepath)
    gdf = gdf.set_crs('EPSG:4326', allow_override=True)
    return gdf


# ============================================================
# 分析函数
# ============================================================

def analyze_water_systems(water_gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """水系分析"""
    results = {
        "water_lines": [],
        "total_length_km": 0,
        "flood_risk_areas": [],
    }

    if water_gdf.empty:
        return results

    for idx, row in water_gdf.iterrows():
        geometry = row.geometry
        length_km = calculate_line_length_km(geometry)
        results["total_length_km"] += length_km

        water_info = {
            "name": row.get('NAME', '未命名水系') if 'NAME' in row else '未命名水系',
            "gb_code": row.get('GB', '') if 'GB' in row else '',
            "length_km": round(length_km, 2),
        }
        results["water_lines"].append(water_info)

        # 计算缓冲区（洪水风险区域）
        buffer_deg = ANALYSIS_PARAMS["water_buffer_m"] / 111000  # 转换为度
        try:
            buffer_geom = geometry.buffer(buffer_deg)
            buffer_area_km2 = buffer_geom.area * 111 * 111  # 粗略转换为平方公里
            results["flood_risk_areas"].append({
                "water_name": water_info["name"],
                "buffer_distance_m": ANALYSIS_PARAMS["water_buffer_m"],
                "risk_area_km2": round(buffer_area_km2, 4),
            })
        except Exception:
            pass

    results["total_length_km"] = round(results["total_length_km"], 2)
    return results


def analyze_road_network(road_gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """道路分析"""
    results = {
        "roads": [],
        "total_length_km": 0,
        "road_coverage_areas": [],
    }

    if road_gdf.empty:
        return results

    for idx, row in road_gdf.iterrows():
        geometry = row.geometry
        length_km = calculate_line_length_km(geometry)
        results["total_length_km"] += length_km

        road_info = {
            "name": row.get('NAME', '未命名道路') if 'NAME' in row else '未命名道路',
            "rn": row.get('RN', '') if 'RN' in row else '',
            "rteg": row.get('RTEG', '') if 'RTEG' in row else '',
            "length_km": round(length_km, 2),
        }
        results["roads"].append(road_info)

        # 计算道路缓冲区（通达区域）
        buffer_deg = ANALYSIS_PARAMS["road_buffer_m"] / 111000
        try:
            buffer_geom = geometry.buffer(buffer_deg)
            buffer_area_km2 = buffer_geom.area * 111 * 111
            results["road_coverage_areas"].append({
                "road_name": road_info["name"],
                "buffer_distance_m": ANALYSIS_PARAMS["road_buffer_m"],
                "coverage_area_km2": round(buffer_area_km2, 4),
            })
        except Exception:
            pass

    results["total_length_km"] = round(results["total_length_km"], 2)
    return results


def analyze_poi_coverage(poi_gdf: gpd.GeoDataFrame, center: Tuple[float, float]) -> Dict[str, Any]:
    """POI 服务覆盖分析"""
    results = {
        "pois": [],
        "service_coverage": [],
        "summary": {
            "total_pois": 0,
            "pois_within_radius": 0,
            "coverage_rate": 0,
        }
    }

    if poi_gdf.empty:
        return results

    radius_m = ANALYSIS_PARAMS["poi_service_radius_m"]

    for idx, row in poi_gdf.iterrows():
        geometry = row.geometry
        if geometry.geom_type != 'Point':
            continue

        poi_coords = (geometry.x, geometry.y)
        distance_m = haversine_distance(center, poi_coords)

        poi_info = {
            "name": row.get('name', '未命名') if 'name' in row else '未命名',
            "category": row.get('category', '') if 'category' in row else '',
            "address": row.get('address', '') if 'address' in row else '',
            "distance_to_center_m": round(distance_m, 1),
            "within_service_radius": distance_m <= radius_m,
        }
        results["pois"].append(poi_info)

        if distance_m <= radius_m:
            results["service_coverage"].append({
                "poi_name": poi_info["name"],
                "distance_m": round(distance_m, 1),
                "category": poi_info["category"],
            })

    total = len(results["pois"])
    within = len(results["service_coverage"])
    results["summary"]["total_pois"] = total
    results["summary"]["pois_within_radius"] = within
    results["summary"]["coverage_rate"] = round(within / total if total > 0 else 0, 4)

    return results


def calculate_suitability_score(
    water_results: Dict,
    road_results: Dict,
    poi_results: Dict,
    center: Tuple[float, float]
) -> Dict[str, Any]:
    """建设适宜性综合评估"""
    # 评分因子权重
    weights = {
        "road_access": 0.4,    # 道路通达性
        "poi_service": 0.3,   # 公共服务覆盖
        "water_risk": 0.3,    # 水系风险（负面影响）
    }

    # 道路通达评分（道路越多越好）
    road_length = road_results.get("total_length_km", 0)
    road_score = min(road_length / 10, 1.0) * 100  # 假设10km道路为满分

    # POI 服务评分
    poi_rate = poi_results.get("summary", {}).get("coverage_rate", 0)
    poi_score = poi_rate * 100

    # 水系风险评分（离水系越远越好）
    water_length = water_results.get("total_length_km", 0)
    flood_areas = water_results.get("flood_risk_areas", [])
    total_flood_area = sum(a.get("risk_area_km2", 0) for a in flood_areas)
    # 水系风险：有水系但不在高风险区为满分
    water_score = max(100 - (total_flood_area * 10), 50) if water_length > 0 else 100

    # 综合评分
    total_score = (
        weights["road_access"] * road_score +
        weights["poi_service"] * poi_score +
        weights["water_risk"] * water_score
    )

    return {
        "road_access_score": round(road_score, 1),
        "poi_service_score": round(poi_score, 1),
        "water_risk_score": round(water_score, 1),
        "total_score": round(total_score, 1),
        "suitability_level": "适宜" if total_score >= 70 else "较适宜" if total_score >= 50 else "需评估",
        "weights": weights,
    }


# ============================================================
# 可视化函数
# ============================================================

def create_folium_map(
    center: Tuple[float, float],
    boundary_gdf: gpd.GeoDataFrame,
    water_gdf: gpd.GeoDataFrame,
    road_gdf: gpd.GeoDataFrame,
    poi_gdf: gpd.GeoDataFrame,
    output_path: Path
) -> None:
    """创建 folium 交互地图"""

    # 创建地图（以金田村为中心）
    m = folium.Map(
        location=[center[1], center[0]],  # folium 使用 (lat, lon)
        zoom_start=13,
        tiles=None,
    )

    # 添加 OpenStreetMap 底图
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        attr='OpenStreetMap contributors'
    ).add_to(m)

    # 添加边界图层
    if not boundary_gdf.empty:
        boundary_json = boundary_gdf.to_json()
        folium.GeoJson(
            boundary_json,
            name='平远县边界',
            style_function=lambda x: {
                'fillColor': '#lightblue',
                'color': '#2b8cbe',
                'weight': 2,
                'fillOpacity': 0.1,
            }
        ).add_to(m)

    # 添加水系图层
    if not water_gdf.empty:
        water_json = water_gdf.to_json()
        folium.GeoJson(
            water_json,
            name='水系',
            style_function=lambda x: {
                'color': '#1f78b4',
                'weight': 3,
                'opacity': 0.8,
            },
            tooltip=folium.GeoJsonTooltip(fields=['NAME', 'GB'], aliases=['名称', '国标码'])
        ).add_to(m)

    # 添加道路图层
    if not road_gdf.empty:
        road_json = road_gdf.to_json()
        folium.GeoJson(
            road_json,
            name='道路',
            style_function=lambda x: {
                'color': '#e31a1c',
                'weight': 2,
                'opacity': 0.8,
            },
            tooltip=folium.GeoJsonTooltip(fields=['NAME', 'RN', 'RTEG'], aliases=['名称', '编号', '等级'])
        ).add_to(m)

    # 添加 POI 图层
    if not poi_gdf.empty:
        poi_group = folium.FeatureGroup(name='POI设施')
        for idx, row in poi_gdf.iterrows():
            if row.geometry.geom_type == 'Point':
                folium.Marker(
                    location=[row.geometry.y, row.geometry.x],
                    popup=folium.Popup(
                        f"<b>{row.get('name', '未命名')}</b><br>"
                        f"类别: {row.get('category', '')}<br>"
                        f"地址: {row.get('address', '')}",
                        max_width=300
                    ),
                    icon=folium.Icon(color='green', icon='info-sign')
                ).add_to(poi_group)
        poi_group.add_to(m)

    # 添加中心点标记
    folium.Marker(
        location=[center[1], center[0]],
        popup='金田村中心',
        icon=folium.Icon(color='red', icon='star')
    ).add_to(m)

    # 添加服务半径圆圈
    folium.Circle(
        location=[center[1], center[0]],
        radius=ANALYSIS_PARAMS["poi_service_radius_m"],
        color='#3388ff',
        fill=True,
        fillColor='#3388ff',
        fillOpacity=0.15,
        popup=f'服务半径: {ANALYSIS_PARAMS["poi_service_radius_m"]}m'
    ).add_to(m)

    # 添加图层控制
    folium.LayerControl().add_to(m)

    # 保存地图
    m.save(str(output_path))
    print(f"[OK] 交互地图已保存: {output_path}")


def create_static_map(
    center: Tuple[float, float],
    boundary_gdf: gpd.GeoDataFrame,
    water_gdf: gpd.GeoDataFrame,
    road_gdf: gpd.GeoDataFrame,
    poi_gdf: gpd.GeoDataFrame,
    output_path: Path
) -> None:
    """创建 matplotlib 静态地图"""

    fig, ax = plt.subplots(figsize=(12, 10))

    # 设置地图范围
    buffer_deg = 0.02  # 约2km
    ax.set_xlim(center[0] - buffer_deg, center[0] + buffer_deg)
    ax.set_ylim(center[1] - buffer_deg, center[1] + buffer_deg)

    # 绘制边界
    if not boundary_gdf.empty:
        boundary_gdf.plot(ax=ax, facecolor='#e6f3ff', edgecolor='#2b8cbe', linewidth=1, alpha=0.5)

    # 绘制水系
    if not water_gdf.empty:
        water_gdf.plot(ax=ax, color='#1f78b4', linewidth=2, label='水系')

    # 绘制道路
    if not road_gdf.empty:
        road_gdf.plot(ax=ax, color='#e31a1c', linewidth=1.5, label='道路')

    # 绘制 POI
    if not poi_gdf.empty:
        poi_points = poi_gdf[poi_gdf.geometry.geom_type == 'Point']
        if not poi_points.empty:
            ax.scatter(
                poi_points.geometry.x,
                poi_points.geometry.y,
                c='green',
                s=100,
                marker='o',
                label='POI设施',
                zorder=5
            )

            # 添加 POI 标签
            for idx, row in poi_points.iterrows():
                name = row.get('name', 'POI') if 'name' in row else 'POI'
                ax.annotate(
                    name,
                    (row.geometry.x, row.geometry.y),
                    xytext=(5, 5),
                    textcoords='offset points',
                    fontsize=8,
                    color='darkgreen'
                )

    # 绘制中心点
    ax.scatter(center[0], center[1], c='red', s=200, marker='*', label='金田村中心', zorder=10)

    # 绘制服务半径圆圈
    radius_deg = ANALYSIS_PARAMS["poi_service_radius_m"] / 111000
    circle = plt.Circle(
        (center[0], center[1]),
        radius_deg,
        color='#3388ff',
        fill=False,
        linewidth=2,
        linestyle='--'
    )
    ax.add_patch(circle)

    # 设置标题和标签
    ax.set_title('金田村 GIS 空间分析图', fontsize=14, fontweight='bold')
    ax.set_xlabel('经度', fontsize=12)
    ax.set_ylabel('纬度', fontsize=12)

    # 添加图例
    ax.legend(loc='upper right', fontsize=10)

    # 添加网格
    ax.grid(True, linestyle='--', alpha=0.5)

    # 设置背景色
    ax.set_facecolor('#f5f5f5')

    # 添加比例尺说明
    ax.text(
        0.02, 0.02,
        '比例尺: 约 1:50000\n服务半径: 500m',
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment='bottom',
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8)
    )

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
    plt.close()

    print(f"[OK] 静态地图已保存: {output_path}")


# ============================================================
# 报告生成
# ============================================================

def generate_report(
    center: Tuple[float, float],
    water_results: Dict,
    road_results: Dict,
    poi_results: Dict,
    suitability_results: Dict,
    output_path: Path
) -> None:
    """生成 Markdown 分析报告"""

    report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    report_lines = [
        "# 金田村 GIS 空间分析报告",
        "",
        f"**生成时间**: {report_time}",
        f"**分析区域**: 金田村（中心坐标: {center[0]}, {center[1]}）",
        "",
        "---",
        "",
        "## 一、数据概述",
        "",
        "本次分析基于以下 GIS 数据：",
        "",
        "**数据来源说明**：",
        "- 高德地图：行政区划边界、POI 设施（点状数据）",
        "- 天地图 WFS：水系线、道路线矢量数据（高德 API 不支持此类矢量数据）",
        "",
        "| 数据类型 | 数据来源 | 数量 | 备注 |",
        "|----------|----------|------|------|",
        f"| 行政边界 | 高德地图 | 1 个 | 平远县边界（高德不支持村级边界） |",
        f"| POI 设施 | 高德地图 | {poi_results.get('summary', {}).get('total_pois', 0)} 个 | 点状设施 |",
        f"| 水系数据 | 天地图 WFS | {len(water_results.get('water_lines', []))} 条 | 线状矢量（高德不支持） |",
        f"| 道路数据 | 天地图 WFS | {len(road_results.get('roads', []))} 条 | 线状矢量（高德不支持） |",
        "",
        "---",
        "",
        "## 二、水系分析",
        "",
        f"### 2.1 水系分布",
        "",
        f"- **总长度**: {water_results.get('total_length_km', 0)} km",
        "",
        "**水系详情**:",
        "",
        "| 名称 | 国标码 | 长度(km) |",
        "|------|--------|----------|",
    ]

    for water in water_results.get("water_lines", []):
        report_lines.append(
            f"| {water.get('name', '未命名')} | {water.get('gb_code', '')} | {water.get('length_km', 0)} |"
        )

    report_lines.extend([
        "",
        "### 2.2 洪水风险区域",
        "",
        f"基于 {ANALYSIS_PARAMS['water_buffer_m']}m 缓冲区分析：",
        "",
        "| 水系名称 | 缓冲距离(m) | 风险面积(km²) |",
        "|----------|-------------|---------------|",
    ])

    for flood in water_results.get("flood_risk_areas", []):
        report_lines.append(
            f"| {flood.get('water_name', '')} | {flood.get('buffer_distance_m', 0)} | {flood.get('risk_area_km2', 0)} |"
        )

    report_lines.extend([
        "",
        "---",
        "",
        "## 三、道路分析",
        "",
        "### 3.1 道路网络",
        "",
        f"- **总长度**: {road_results.get('total_length_km', 0)} km",
        "",
        "**道路详情**:",
        "",
        "| 名称 | 编号 | 等级 | 长度(km) |",
        "|------|------|------|----------|",
    ])

    for road in road_results.get("roads", []):
        report_lines.append(
            f"| {road.get('name', '未命名')} | {road.get('rn', '')} | {road.get('rteg', '')} | {road.get('length_km', 0)} |"
        )

    report_lines.extend([
        "",
        "### 3.2 道路通达区域",
        "",
        f"基于 {ANALYSIS_PARAMS['road_buffer_m']}m 缓冲区分析：",
        "",
        "| 道路名称 | 缓冲距离(m) | 覆盖面积(km²) |",
        "|----------|-------------|---------------|",
    ])

    for coverage in road_results.get("road_coverage_areas", []):
        report_lines.append(
            f"| {coverage.get('road_name', '')} | {coverage.get('buffer_distance_m', 0)} | {coverage.get('coverage_area_km2', 0)} |"
        )

    report_lines.extend([
        "",
        "---",
        "",
        "## 四、POI 服务覆盖分析",
        "",
        f"### 4.1 设施分布",
        "",
        f"服务半径设定: {ANALYSIS_PARAMS['poi_service_radius_m']}m",
        "",
        f"- **POI 总数**: {poi_results.get('summary', {}).get('total_pois', 0)}",
        f"- **范围内设施**: {poi_results.get('summary', {}).get('pois_within_radius', 0)}",
        f"- **覆盖率**: {poi_results.get('summary', {}).get('coverage_rate', 0) * 100:.1f}%",
        "",
        "**POI 详情**:",
        "",
        "| 名称 | 类别 | 地址 | 距中心距离(m) | 是否覆盖 |",
        "|------|------|------|---------------|----------|",
    ])

    for poi in poi_results.get("pois", []):
        within = "✓" if poi.get("within_service_radius", False) else "✗"
        report_lines.append(
            f"| {poi.get('name', '')} | {poi.get('category', '')[:30]} | {poi.get('address', '')} | {poi.get('distance_to_center_m', 0)} | {within} |"
        )

    report_lines.extend([
        "",
        "---",
        "",
        "## 五、建设适宜性综合评估",
        "",
        "### 5.1 评分因子",
        "",
        "| 因子 | 权重 | 评分 | 说明 |",
        "|------|------|------|------|",
        f"| 道路通达性 | {suitability_results.get('weights', {}).get('road_access', 0)} | {suitability_results.get('road_access_score', 0)} | 基于道路长度 |",
        f"| 公共服务覆盖 | {suitability_results.get('weights', {}).get('poi_service', 0)} | {suitability_results.get('poi_service_score', 0)} | 基于POI覆盖率 |",
        f"| 水系风险 | {suitability_results.get('weights', {}).get('water_risk', 0)} | {suitability_results.get('water_risk_score', 0)} | 基于洪水风险区 |",
        "",
        "### 5.2 综合评估结果",
        "",
        f"- **综合评分**: {suitability_results.get('total_score', 0)}",
        f"- **适宜性等级**: **{suitability_results.get('suitability_level', '')}**",
        "",
        "---",
        "",
        "## 六、结论与建议",
        "",
        "### 6.1 主要发现",
        "",
        f"1. 水系总长度 {water_results.get('total_length_km', 0)} km，需关注洪水风险区域规划。",
        f"2. 道路总长度 {road_results.get('total_length_km', 0)} km，道路通达性良好。",
        f"3. POI 覆盖率 {poi_results.get('summary', {}).get('coverage_rate', 0) * 100:.1f}%，公共服务设施覆盖情况需进一步提升。",
        "",
        "### 6.2 规划建议",
        "",
        f"- 建设适宜性评估为 **{suitability_results.get('suitability_level', '')}**，可结合具体地块进行详细评估。",
        "- 建议在水系缓冲区范围外进行建设开发。",
        "- 建议增加公共服务设施，提升 POI 覆盖率。",
        "",
        "---",
        "",
        "## 附录",
        "",
        "### A. 输出文件",
        "",
        "| 文件 | 路径 |",
        "|------|------|",
        f"| 交互地图 | `{OUTPUT_FILES['interactive_map'].relative_to(BASE_DIR)}` |",
        f"| 静态地图 | `{OUTPUT_FILES['static_map'].relative_to(BASE_DIR)}` |",
        f"| 分析结果JSON | `{OUTPUT_FILES['results'].relative_to(BASE_DIR)}` |",
        "",
        "*报告由 GIS 分析脚本自动生成*",
    ])

    # 写入文件
    report_content = "\n".join(report_lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"[OK] 分析报告已保存: {output_path}")


def save_results_json(
    center: Tuple[float, float],
    water_results: Dict,
    road_results: Dict,
    poi_results: Dict,
    suitability_results: Dict,
    output_path: Path
) -> None:
    """保存分析结果为 JSON"""

    results = {
        "analysis_time": datetime.now().isoformat(),
        "center": {"lon": center[0], "lat": center[1]},
        "params": ANALYSIS_PARAMS,
        "water_analysis": water_results,
        "road_analysis": road_results,
        "poi_analysis": poi_results,
        "suitability_assessment": suitability_results,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[OK] 分析结果已保存: {output_path}")


def save_metadata(output_path: Path) -> None:
    """保存元数据"""

    metadata = {
        "analysis_name": "金田村 GIS 空间分析",
        "created_at": datetime.now().isoformat(),
        "data_sources": {
            "water": "天地图 WFS 服务",
            "road": "天地图 WFS 服务",
            "poi": "高德地图 POI API",
            "boundary": "高德地图行政区划 API",
        },
        "outputs": {
            "interactive_map": str(OUTPUT_FILES["interactive_map"]),
            "static_map": str(OUTPUT_FILES["static_map"]),
            "report": str(OUTPUT_FILES["report"]),
            "results": str(OUTPUT_FILES["results"]),
        },
        "analysis_params": ANALYSIS_PARAMS,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"[OK] 元数据已保存: {output_path}")


# ============================================================
# 主函数
# ============================================================

def main():
    """主分析流程"""
    print("=" * 60)
    print("金田村 GIS 空间分析")
    print("=" * 60)

    # Step 1: 数据加载
    print("\n[Step 1] 加载 GeoJSON 数据...")

    center_gdf = load_geojson(DATA_FILES["center"])
    boundary_gdf = load_geojson(DATA_FILES["boundary"])
    poi_gdf = load_geojson(DATA_FILES["pois"])
    water_gdf = load_geojson(DATA_FILES["water_line"])
    road_gdf = load_geojson(DATA_FILES["road_line"])

    print(f"  - 中心点: {len(center_gdf)} 个")
    print(f"  - 边界: {len(boundary_gdf)} 个要素")
    print(f"  - POI: {len(poi_gdf)} 个")
    print(f"  - 水系: {len(water_gdf)} 条")
    print(f"  - 道路: {len(road_gdf)} 条")

    # Step 2: 空间分析
    print("\n[Step 2] 执行空间分析...")

    water_results = analyze_water_systems(water_gdf)
    print(f"  - 水系总长度: {water_results['total_length_km']} km")

    road_results = analyze_road_network(road_gdf)
    print(f"  - 道路总长度: {road_results['total_length_km']} km")

    poi_results = analyze_poi_coverage(poi_gdf, JINTIAN_CENTER)
    print(f"  - POI 覆盖率: {poi_results['summary']['coverage_rate'] * 100:.1f}%")

    suitability_results = calculate_suitability_score(
        water_results, road_results, poi_results, JINTIAN_CENTER
    )
    print(f"  - 综合评分: {suitability_results['total_score']}")
    print(f"  - 适宜性等级: {suitability_results['suitability_level']}")

    # Step 3: 可视化
    print("\n[Step 3] 生成可视化...")

    create_folium_map(
        JINTIAN_CENTER, boundary_gdf, water_gdf, road_gdf, poi_gdf,
        OUTPUT_FILES["interactive_map"]
    )

    create_static_map(
        JINTIAN_CENTER, boundary_gdf, water_gdf, road_gdf, poi_gdf,
        OUTPUT_FILES["static_map"]
    )

    # Step 4: 报告生成
    print("\n[Step 4] 生成分析报告...")

    generate_report(
        JINTIAN_CENTER, water_results, road_results, poi_results, suitability_results,
        OUTPUT_FILES["report"]
    )

    save_results_json(
        JINTIAN_CENTER, water_results, road_results, poi_results, suitability_results,
        OUTPUT_FILES["results"]
    )

    save_metadata(OUTPUT_FILES["metadata"])

    # 完成
    print("\n" + "=" * 60)
    print("分析完成！")
    print("=" * 60)
    print("\n输出文件:")
    print(f"  1. 交互地图: {OUTPUT_FILES['interactive_map']}")
    print(f"  2. 静态地图: {OUTPUT_FILES['static_map']}")
    print(f"  3. 分析报告: {OUTPUT_FILES['report']}")
    print(f"  4. 分析结果: {OUTPUT_FILES['results']}")
    print(f"  5. 元数据: {OUTPUT_FILES['metadata']}")

    return {
        "water": water_results,
        "road": road_results,
        "poi": poi_results,
        "suitability": suitability_results,
    }


if __name__ == "__main__":
    main()