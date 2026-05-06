#!/usr/bin/env python3
"""
金田村 GIS 数据提取脚本
从 ArcGIS File Geodatabase (GDB) 提取图层并转换为 GeoJSON
"""

import geopandas as gpd
import json
from pathlib import Path
from datetime import datetime

# GDB 路径
GDB_PATHS = {
    '现状': Path('docs/references/村庄规划总图/金田村村庄规划工程文件/1.村庄用地现状图/图层.gdb'),
    '规划': Path('docs/references/村庄规划总图/金田村村庄规划工程文件/2.村庄规划总图/图层.gdb'),
}

# 输出目录
OUTPUT_DIR = Path('docs/gis/jintian_boundary')

# 要提取的全部图层配置
EXTRACT_LAYERS = {
    '现状': [
        'JT_行政区划_PBL_20220925',         # 村域边界
        'JT_农村居民点外道路_LJJ_202201004', # 道路现状
        'JT_现状地类图斑_LJJ_20221018',      # 土地利用现状
        'PY_行政区划界线_LJJ_20220925',      # 行政界线
        'JT_现状注记_LJJ_20221216',          # 注记
    ],
    '规划': [
        'JT_行政区划_PBL_20220925',         # 村域边界
        'JT_期末地类_LJJ_20221212',         # 土地利用规划
        'JT_农村居民点外道路_LJJ_20221108', # 道路规划
        'JT_地质灾害点_LJJ_20221212',       # 地质灾害点
        'JT_有条件建设区_LJJ_20221212',     # 有条件建设区
        'JT_永久基本农田保护红线_LJJ_20221212', # 农田保护红线
        'JT_历史文化保护线_LJJ_20221212',   # 历史文化保护线
        'JT_生态保护红线_LJJ_20221212',     # 生态保护红线
        'JT_注记_LJJ_20221216',             # 注记
    ],
}

# 输出文件名映射
OUTPUT_NAMES = {
    ('现状', 'JT_行政区划_PBL_20220925'): 'boundary_current.geojson',
    ('现状', 'JT_农村居民点外道路_LJJ_202201004'): 'road_current.geojson',
    ('现状', 'JT_现状地类图斑_LJJ_20221018'): 'landuse_current.geojson',
    ('现状', 'PY_行政区划界线_LJJ_20220925'): 'admin_boundary_line.geojson',
    ('现状', 'JT_现状注记_LJJ_20221216'): 'annotation_current.geojson',
    ('规划', 'JT_行政区划_PBL_20220925'): 'boundary.geojson',
    ('规划', 'JT_期末地类_LJJ_20221212'): 'landuse_planned.geojson',
    ('规划', 'JT_农村居民点外道路_LJJ_20221108'): 'road_planned.geojson',
    ('规划', 'JT_地质灾害点_LJJ_20221212'): 'geological_hazard_points.geojson',
    ('规划', 'JT_有条件建设区_LJJ_20221212'): 'construction_zone.geojson',
    ('规划', 'JT_永久基本农田保护红线_LJJ_20221212'): 'farmland_protection.geojson',
    ('规划', 'JT_历史文化保护线_LJJ_20221212'): 'historical_protection.geojson',
    ('规划', 'JT_生态保护红线_LJJ_20221212'): 'ecological_protection.geojson',
    ('规划', 'JT_注记_LJJ_20221216'): 'annotation_planned.geojson',
}


def list_gdb_layers(gdb_path: Path) -> list:
    """列出 GDB 中所有图层"""
    try:
        layers = gpd.list_layers(gdb_path)
        print(f"  可用图层: {layers['name'].tolist()}")
        return layers['name'].tolist()
    except Exception as e:
        print(f"  列出图层失败: {e}")
        return []


def extract_layer(gdb_path: Path, layer_name: str) -> gpd.GeoDataFrame:
    """从 GDB 提取单个图层"""
    try:
        gdf = gpd.read_file(gdb_path, layer=layer_name)
        print(f"    原始坐标系: {gdf.crs}")
        print(f"    图层记录数: {len(gdf)}")
        print(f"    属性字段: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        print(f"    提取失败: {e}")
        return None


def convert_to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """转换坐标系到 WGS84 (EPSG:4326)"""
    if gdf.crs is None:
        print("    警告: 无坐标系信息，假设为 EPSG:4527")
        gdf = gdf.set_crs('EPSG:4527')

    if gdf.crs.to_epsg() != 4326:
        print(f"    转换 {gdf.crs} -> EPSG:4326")
        gdf = gdf.to_crs('EPSG:4326')

    return gdf


def save_geojson(gdf: gpd.GeoDataFrame, output_path: Path):
    """保存为 GeoJSON"""
    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存 GeoJSON
    gdf.to_file(output_path, driver='GeoJSON')
    print(f"    已保存: {output_path}")

    # 输出坐标范围验证
    bounds = gdf.total_bounds
    print(f"    坐标范围: [{bounds[0]:.6f}, {bounds[1]:.6f}] - [{bounds[2]:.6f}, {bounds[3]:.6f}]")


def create_metadata(output_dir: Path, extracted_data: dict):
    """创建数据元信息文件"""
    metadata = {
        'source': '金田村村庄规划工程文件',
        'extracted_at': datetime.now().isoformat(),
        'coordinate_system': 'EPSG:4326 (WGS84)',
        'source_crs': 'EPSG:4527 (CGCS2000 / 3-degree GK zone 7)',
        'village': {
            'name': '金田村委会',
            'code': '441426108004',
            'area_km2': 23.53,
        },
        'files': {},
    }

    for file_name, info in extracted_data.items():
        metadata['files'][file_name] = {
            'source_gdb': info['gdb'],
            'source_layer': info['layer'],
            'records': info['records'],
            'geometry_type': info['geometry_type'],
        }

    metadata_path = output_dir / 'metadata.json'
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"\n元数据已保存: {metadata_path}")


def main():
    print("=" * 60)
    print("金田村 GIS 数据提取")
    print("=" * 60)

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    extracted_data = {}

    for gdb_type, gdb_path in GDB_PATHS.items():
        print(f"\n处理 {gdb_type} 图 GDB: {gdb_path}")

        if not gdb_path.exists():
            print(f"  错误: GDB 不存在")
            continue

        # 列出可用图层
        available_layers = list_gdb_layers(gdb_path)

        # 提取配置中的图层
        for layer_name in EXTRACT_LAYERS.get(gdb_type, []):
            print(f"\n  提取图层: {layer_name}")

            if layer_name not in available_layers:
                print(f"    警告: 图层不存在，跳过")
                continue

            # 提取图层
            gdf = extract_layer(gdb_path, layer_name)
            if gdf is None:
                continue

            # 转换坐标系
            gdf = convert_to_wgs84(gdf)

            # 确定输出文件名
            output_key = (gdb_type, layer_name)
            output_name = OUTPUT_NAMES.get(output_key, f"{layer_name}.geojson")
            output_path = OUTPUT_DIR / output_name

            # 保存 GeoJSON
            save_geojson(gdf, output_path)

            # 记录提取信息
            extracted_data[output_name] = {
                'gdb': gdb_type,
                'layer': layer_name,
                'records': len(gdf),
                'geometry_type': gdf.geometry.iloc[0].geom_type if len(gdf) > 0 else 'Unknown',
            }

    # 创建元数据
    create_metadata(OUTPUT_DIR, extracted_data)

    print("\n" + "=" * 60)
    print("提取完成!")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"生成文件数: {len(extracted_data) + 1}")  # +1 for metadata.json
    print("=" * 60)


if __name__ == '__main__':
    main()