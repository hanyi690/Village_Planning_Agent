#!/usr/bin/env python3
"""从SVG文件提取建设项目布局数据转换为GeoJSON"""

import xml.etree.ElementTree as ET
import json
import re
from pathlib import Path
from shapely.geometry import mapping, Point, LineString, Polygon
import geopandas as gpd
from typing import List, Dict, Tuple


def parse_svg_path(d: str) -> List[Tuple[float, float]]:
    """解析SVG path的d属性，提取坐标点"""
    coords = []

    # 匹配所有坐标数值
    # SVG path格式: M x,y L x,y L x,y Z 等
    pattern = r'[-\d.]+'
    numbers = [float(n) for n in re.findall(pattern, d)]

    # 坐标成对出现
    for i in range(0, len(numbers) - 1, 2):
        coords.append((numbers[i], numbers[i + 1]))

    return coords


def svg_coords_to_cad(svg_x: float, svg_y: float,
                      viewBox: Tuple[float, float, float, float],
                      strip_band: bool = True) -> Tuple[float, float]:
    """将SVG坐标转换为CAD原始坐标

    Args:
        strip_band: 是否去掉X坐标中的带号前缀
    """
    vb_x, vb_y, vb_w, vb_h = viewBox
    # SVG viewBox: 原始坐标系的左下角和宽度高度
    # SVG中Y轴向下，CAD中Y轴向上，需要反转
    cad_x = vb_x + svg_x
    cad_y = vb_y + vb_h - svg_y  # Y轴反转

    # 去掉X坐标中的带号前缀（前两位）
    # CGCS2000 Gauss-Kruger带号格式: X = 带号*1000000 + 东向坐标
    if strip_band and cad_x > 10000000:
        band = int(str(int(cad_x))[:2])
        cad_x = cad_x - band * 1000000

    return cad_x, cad_y


def extract_svg_entities(svg_path: Path, output_dir: Path) -> tuple:
    """从SVG提取几何实体"""

    # 解析SVG
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # 获取viewBox
    svg_elem = root
    viewBox_str = svg_elem.get('viewBox', '0 0 1000 1000')
    viewBox = [float(v) for v in viewBox_str.split()]
    print(f"ViewBox: {viewBox}")
    print(f"原始坐标范围: X={viewBox[0]:.2f}~{viewBox[0]+viewBox[2]:.2f}, Y={viewBox[1]:.2f}~{viewBox[1]+viewBox[3]:.2f}")

    # 存储各类实体
    points: List[Dict] = []
    lines: List[Dict] = []
    polygons: List[Dict] = []
    texts: List[Dict] = []

    # 统计信息
    entity_count = 0
    layer_info = {}

    # 预定义的图层颜色映射
    color_layer_map = {
        'black': '默认',
        'red': '建设项目红线',
        '#006081': '规划道路',
        'blue': '新增公共服务设施',
        'green': '保留公共服务设施',
    }

    # 解析所有元素
    for elem in root.iter():
        tag = elem.tag.replace('{http://www.w3.org/2000/svg}', '')

        if tag == 'path':
            d = elem.get('d', '')
            style = elem.get('style', '')

            # 从style提取颜色来判断图层
            stroke_color = 'black'
            if 'stroke:' in style:
                match = re.search(r'stroke:([^;]+)', style)
                if match:
                    stroke_color = match.group(1).strip()

            layer = color_layer_map.get(stroke_color, stroke_color)

            # 解析坐标
            coords = parse_svg_path(d)
            if len(coords) < 2:
                continue

            # 转换为CAD坐标
            cad_coords = [svg_coords_to_cad(x, y, viewBox) for x, y in coords]

            # 判断是闭合还是开放
            is_closed = d.strip().endswith('Z') or (len(coords) >= 3 and coords[0] == coords[-1])

            if is_closed and len(cad_coords) >= 3:
                # 创建多边形
                polygons.append({
                    'geometry': mapping(Polygon(cad_coords)),
                    'properties': {'layer': layer, 'type': 'polygon', 'color': stroke_color}
                })
                if layer not in layer_info:
                    layer_info[layer] = {'count': 0, 'types': set()}
                layer_info[layer]['count'] += 1
                layer_info[layer]['types'].add('polygon')
            else:
                # 创建线
                lines.append({
                    'geometry': mapping(LineString(cad_coords)),
                    'properties': {'layer': layer, 'type': 'line', 'color': stroke_color}
                })
                if layer not in layer_info:
                    layer_info[layer] = {'count': 0, 'types': set()}
                layer_info[layer]['count'] += 1
                layer_info[layer]['types'].add('line')

            entity_count += 1

        elif tag == 'text':
            x = float(elem.get('x', '0'))
            y = float(elem.get('y', '0'))

            # 获取文本内容（处理Unicode编码）
            content = elem.text or ''

            # 转换为CAD坐标
            cad_x, cad_y = svg_coords_to_cad(x, y, viewBox)

            texts.append({
                'geometry': mapping(Point(cad_x, cad_y)),
                'properties': {'layer': 'annotation', 'text': content, 'type': 'annotation'}
            })

            if 'annotation' not in layer_info:
                layer_info['annotation'] = {'count': 0, 'types': set()}
            layer_info['annotation']['count'] += 1
            layer_info['annotation']['types'].add('text')

            entity_count += 1

    # 打印图层统计
    print(f"\n图层统计:")
    for layer, info in sorted(layer_info.items()):
        types_str = ', '.join(sorted(info['types']))
        print(f"  {layer}: {info['count']}个实体 ({types_str})")

    # 保存为GeoJSON，并进行坐标系转换
    output_dir.mkdir(parents=True, exist_ok=True)

    # CGCS2000 / 3-degree Gauss-Kruger CM格式（假东=0）
    # 根据X坐标前两位判断带号
    x_min = viewBox[0]
    band = int(str(int(x_min))[:2])

    # EPSG代码映射：带号 -> CM格式EPSG（假东=0）
    # 因为去掉了带号前缀，坐标不含假东500000
    # 37带 = EPSG:4520 (中央111°)
    # 38带 = EPSG:4521 (中央114°)
    # 39带 = EPSG:4522 (中央117°)
    epsg_map = {37: 'EPSG:4520', 38: 'EPSG:4521', 39: 'EPSG:4522'}
    crs = epsg_map.get(band, 'EPSG:4520')

    print(f"\n检测到带号: {band} -> 使用 {crs} (CM格式，假东=0)")

    save_geojson(points, output_dir / 'project_points.geojson', crs)
    save_geojson(lines, output_dir / 'project_lines.geojson', crs)
    save_geojson(polygons, output_dir / 'project_polygons.geojson', crs)
    save_geojson(texts, output_dir / 'project_annotation.geojson', crs)

    # 保存图层信息
    layer_metadata = {
        'source_file': str(svg_path),
        'viewBox': viewBox,
        'coordinate_system': crs,
        'total_entities': entity_count,
        'layers': {k: {'count': v['count'], 'types': list(v['types'])}
                   for k, v in layer_info.items()}
    }
    with open(output_dir / 'layer_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(layer_metadata, f, ensure_ascii=False, indent=2)

    return len(points), len(lines), len(polygons), len(texts)


def save_geojson(features: List[Dict], path: Path, crs: str = None):
    """保存GeoJSON文件，支持坐标系转换"""
    if not features:
        # 创建空文件
        geojson = {'type': 'FeatureCollection', 'features': []}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {path} (0个实体)")
        return

    # 尝试坐标系转换
    if crs:
        try:
            gdf = gpd.GeoDataFrame.from_features(features, crs=crs)
            gdf = gdf.to_crs('EPSG:4326')
            gdf.to_file(path, driver='GeoJSON')
            print(f"  已保存: {path} ({len(features)}个实体, 坐标系转换: {crs} -> WGS84)")
            return
        except Exception as e:
            print(f"  坐标系转换失败: {e}, 保存原始坐标")

    # 直接保存
    geojson = {
        'type': 'FeatureCollection',
        'features': [
            {'type': 'Feature', 'geometry': f['geometry'], 'properties': f['properties']}
            for f in features
        ]
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"  已保存: {path} ({len(features)}个实体)")


def main():
    svg_path = Path('docs/gis/jintian_dxf/project_layout_clean.svg')
    output_dir = Path('docs/gis/jintian_boundary')

    if not svg_path.exists():
        print(f"SVG文件不存在: {svg_path}")
        print("请先运行 dwg2SVG.exe 转换DWG文件")
        return

    print(f"读取SVG文件: {svg_path}")
    print("=" * 50)

    # 提取实体
    print("\n提取几何实体...")
    counts = extract_svg_entities(svg_path, output_dir)

    print(f"\n" + "=" * 50)
    print(f"提取完成!")
    print(f"  点: {counts[0]}")
    print(f"  线: {counts[1]}")
    print(f"  面: {counts[2]}")
    print(f"  注记: {counts[3]}")
    print(f"\n输出目录: {output_dir}")


if __name__ == '__main__':
    main()