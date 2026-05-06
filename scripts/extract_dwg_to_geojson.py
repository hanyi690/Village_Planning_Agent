#!/usr/bin/env python3
"""从DXF提取几何数据转换为GeoJSON

重要说明：
- DXF原始坐标含37带号，但实际应使用EPSG:4527（39带）
- 需要应用固定偏移量将DXF坐标对齐到GDB坐标系
- 偏移量: X + 1789261, Y + 94888
"""

import ezdxf
import json
from pathlib import Path
from shapely.geometry import mapping, Point, LineString, Polygon
import geopandas as gpd
from typing import List, Dict, Any

# 固定偏移量：将DXF的37带坐标对齐到GDB的39带坐标系
X_SHIFT = 1789261  # DXF到GDB的X偏移
Y_SHIFT = 94888    # DXF到GDB的Y偏移


def apply_shift_to_coords(coords: List[tuple]) -> List[tuple]:
    """应用固定偏移量将DXF坐标对齐到GDB坐标系"""
    return [(x + X_SHIFT, y + Y_SHIFT) for x, y in coords]


def apply_shift_to_point(x: float, y: float) -> tuple:
    """应用偏移量到单个点坐标"""
    return (x + X_SHIFT, y + Y_SHIFT)


def extract_entities(dxf_path: Path, output_dir: Path, apply_shift: bool = False) -> tuple:
    """提取DXF中的所有实体，支持坐标偏移处理"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    points: List[Dict] = []
    lines: List[Dict] = []
    texts: List[Dict] = []
    polygons: List[Dict] = []

    print(f"正在解析DXF实体...")
    entity_count = 0
    layer_info = {}

    for entity in msp.query('*'):
        dxftype = entity.dxftype()
        layer = entity.dxf.layer

        if layer not in layer_info:
            layer_info[layer] = {'count': 0, 'types': set()}
        layer_info[layer]['count'] += 1
        layer_info[layer]['types'].add(dxftype)

        try:
            if dxftype == 'POINT':
                loc = entity.dxf.location
                x, y = loc.x, loc.y
                if apply_shift:
                    x, y = apply_shift_to_point(x, y)
                points.append({
                    'geometry': mapping(Point(x, y)),
                    'properties': {'layer': layer, 'type': 'point'}
                })

            elif dxftype == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                coords = [(start.x, start.y), (end.x, end.y)]
                if apply_shift:
                    coords = apply_shift_to_coords(coords)
                lines.append({
                    'geometry': mapping(LineString(coords)),
                    'properties': {'layer': layer, 'type': 'line'}
                })

            elif dxftype == 'LWPOLYLINE':
                coords = [(p[0], p[1]) for p in entity.get_points()]
                if apply_shift:
                    coords = apply_shift_to_coords(coords)
                if len(coords) >= 2:
                    if entity.closed:
                        polygons.append({
                            'geometry': mapping(Polygon(coords)),
                            'properties': {'layer': layer, 'type': 'polygon'}
                        })
                    else:
                        lines.append({
                            'geometry': mapping(LineString(coords)),
                            'properties': {'layer': layer, 'type': 'polyline'}
                        })

            elif dxftype == 'POLYLINE':
                coords = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                if apply_shift:
                    coords = apply_shift_to_coords(coords)
                if len(coords) >= 2:
                    if entity.is_closed:
                        polygons.append({
                            'geometry': mapping(Polygon(coords)),
                            'properties': {'layer': layer, 'type': 'polygon'}
                        })
                    else:
                        lines.append({
                            'geometry': mapping(LineString(coords)),
                            'properties': {'layer': layer, 'type': 'polyline'}
                        })

            elif dxftype == 'TEXT':
                insert = entity.dxf.insert
                x, y = insert.x, insert.y
                if apply_shift:
                    x, y = apply_shift_to_point(x, y)
                content = entity.dxf.text
                texts.append({
                    'geometry': mapping(Point(x, y)),
                    'properties': {'layer': layer, 'text': content, 'type': 'annotation'}
                })

            elif dxftype == 'MTEXT':
                insert = entity.dxf.insertion_point
                x, y = insert.x, insert.y
                if apply_shift:
                    x, y = apply_shift_to_point(x, y)
                content = entity.text
                texts.append({
                    'geometry': mapping(Point(x, y)),
                    'properties': {'layer': layer, 'text': content, 'type': 'annotation'}
                })

            elif dxftype in ('CIRCLE', 'ARC', 'SPLINE', 'ELLIPSE'):
                try:
                    coords = list(entity.flattening(0.1))
                    if apply_shift:
                        coords = apply_shift_to_coords(coords)
                    if len(coords) >= 2:
                        lines.append({
                            'geometry': mapping(LineString(coords)),
                            'properties': {'layer': layer, 'type': dxftype.lower()}
                        })
                except:
                    pass

            entity_count += 1

        except Exception as e:
            pass

    # 打印图层统计
    print(f"\n图层统计:")
    for layer, info in sorted(layer_info.items()):
        types_str = ', '.join(sorted(info['types']))
        print(f"  {layer}: {info['count']}个实体 ({types_str})")

    # 保存为GeoJSON（带坐标系转换）
    output_dir.mkdir(parents=True, exist_ok=True)

    # 使用EPSG:4527（39带）坐标系，与GDB数据一致
    crs = 'EPSG:4527' if apply_shift else None
    save_geojson(points, output_dir / 'project_points.geojson', crs)
    save_geojson(lines, output_dir / 'project_lines.geojson', crs)
    save_geojson(polygons, output_dir / 'project_polygons.geojson', crs)
    save_geojson(texts, output_dir / 'project_annotation.geojson', crs)

    # 保存图层信息
    layer_metadata = {
        'source_file': str(dxf_path),
        'total_entities': entity_count,
        'layers': {k: {'count': v['count'], 'types': list(v['types'])}
                   for k, v in layer_info.items()}
    }
    with open(output_dir / 'layer_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(layer_metadata, f, ensure_ascii=False, indent=2)

    return len(points), len(lines), len(polygons), len(texts)


def save_geojson(features: List[Dict], path: Path, crs: str = None):
    """保存GeoJSON文件"""
    if not features:
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


def detect_coordinate_system(dxf_path: Path) -> tuple:
    """检测DXF文件坐标系并返回(CRS代码, 是否需要应用偏移)

    重要说明：
    - DXF原始坐标含37带号，但实际应使用EPSG:4527（39带）
    - 需要应用固定偏移量将DXF坐标对齐到GDB坐标系
    """
    doc = ezdxf.readfile(dxf_path)

    # 检查HEADER中的坐标系信息
    header = doc.header

    # CGCS2000常见EPSG代码
    possible_crs = None
    apply_shift = False

    try:
        extmin = header.get('$EXTMIN')
        extmax = header.get('$EXTMAX')
        if extmin and extmax:
            x_min, y_min = extmin[0], extmin[1]
            x_max, y_max = extmax[0], extmax[1]

            # 如果X坐标值在37带范围（37,000,000 ~ 38,000,000）
            # 需要应用偏移量对齐到39带坐标系（EPSG:4527）
            if x_min > 37000000 and x_min < 38000000:
                apply_shift = True
                # 使用EPSG:4527（39带），与GDB数据一致
                possible_crs = 'EPSG:4527'
                print(f"检测到DXF坐标含37带号")
                print(f"原始坐标范围: X={x_min:.2f}~{x_max:.2f}, Y={y_min:.2f}~{y_max:.2f}")
                print(f"将应用偏移量: X+{X_SHIFT}, Y+{Y_SHIFT}")
                print(f"目标坐标系: EPSG:4527（39带）")

                # 验证转换结果
                sample_x = x_min + X_SHIFT
                sample_y = y_min + Y_SHIFT
                print(f"偏移后坐标: X={sample_x:.2f}, Y={sample_y:.2f}")
            elif abs(x_min) > 100000 or abs(y_min) > 100000:
                # 中国常见投影坐标系（不含带号）
                possible_crs = 'EPSG:4527'
                print(f"检测到投影坐标系，坐标范围: X={x_min:.2f}, Y={y_min:.2f}")
                print(f"假设为 CGCS2000 39带 (EPSG:4527)")
            else:
                print(f"检测到地理坐标系，坐标范围: X={x_min:.2f}, Y={y_min:.2f}")
    except:
        pass

    return possible_crs, apply_shift


def strip_zone_from_coords(coords: List[tuple], zone_prefix: int = 37) -> List[tuple]:
    """从坐标中去掉带号前缀（已弃用，保留作为参考）"""
    return [(x - zone_prefix * 1000000, y) for x, y in coords]


def main():
    # DXF文件路径 - ImageToStl.com转换版本
    dxf_path = Path('docs/references/村庄规划总图/金田村村庄规划工程文件/3.村庄建设项目布局规划图/ImageToStl.com_03金田村建设项目布局规划图.dxf')

    if not dxf_path.exists():
        print(f"DXF文件不存在: {dxf_path}")
        return

    output_dir = Path('docs/gis/jintian_boundary')

    print(f"读取DXF文件: {dxf_path}")
    print("=" * 50)

    # 检测坐标系
    crs, apply_shift = detect_coordinate_system(dxf_path)

    # 提取实体
    print("\n提取几何实体...")
    counts = extract_entities(dxf_path, output_dir, apply_shift)

    print(f"\n" + "=" * 50)
    print(f"提取完成!")
    print(f"  点: {counts[0]}")
    print(f"  线: {counts[1]}")
    print(f"  面: {counts[2]}")
    print(f"  注记: {counts[3]}")
    print(f"\n输出目录: {output_dir}")


if __name__ == '__main__':
    main()