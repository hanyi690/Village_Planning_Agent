"""
GIS 数据解析模块

统一解析多种 GIS 格式，输出标准 GeoJSON。
支持 GeoJSON、Shapefile、KML/KMZ、GeoTIFF 等格式。

依赖库:
- geopandas: Shapefile 解析和坐标转换
- fastkml: KML 解析
- rasterio: GeoTIFF 解析（可选）
"""

import json
import os
import tempfile
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """解析结果数据结构"""
    geojson: Dict[str, Any]
    properties: List[str] = field(default_factory=list)
    crs: str = "EPSG:4326"
    feature_count: int = 0
    file_type: str = ""
    source_file: str = ""
    error: Optional[str] = None
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "geojson": self.geojson,
            "properties": self.properties,
            "crs": self.crs,
            "feature_count": self.feature_count,
            "file_type": self.file_type,
            "source_file": self.source_file,
            "error": self.error,
            "success": self.success,
        }


class GISDataParser:
    """统一 GIS 数据解析器"""

    SUPPORTED_FORMATS = {
        'geojson': ['.geojson', '.json'],
        'shapefile': ['.shp'],
        'kml': ['.kml'],
        'kmz': ['.kmz'],
        'geotiff': ['.tif', '.tiff'],
    }

    def __init__(self):
        """初始化解析器"""
        self._check_dependencies()

    def _check_dependencies(self):
        """检查依赖库是否可用"""
        self._has_geopandas = False
        self._has_fastkml = False
        self._has_rasterio = False

        try:
            import geopandas as gpd
            self._has_geopandas = True
            logger.debug("[GISParser] geopandas 可用")
        except ImportError:
            logger.warning("[GISParser] geopandas 未安装，Shapefile 解析受限")

        try:
            from fastkml import kml
            self._has_fastkml = True
            logger.debug("[GISParser] fastkml 可用")
        except ImportError:
            logger.warning("[GISParser] fastkml 未安装，KML 解析受限")

        try:
            import rasterio
            self._has_rasterio = True
            logger.debug("[GISParser] rasterio 可用")
        except ImportError:
            logger.warning("[GISParser] rasterio 未安装，GeoTIFF 解析受限")

    def detect_file_type(self, file_path: str) -> Optional[str]:
        """
        根据文件扩展名检测文件类型

        Args:
            file_path: 文件路径

        Returns:
            文件类型键名，无法识别返回 None
        """
        ext = Path(file_path).suffix.lower()
        for format_name, extensions in self.SUPPORTED_FORMATS.items():
            if ext in extensions:
                return format_name
        return None

    def parse(self, file_path: str, file_type: Optional[str] = None) -> ParseResult:
        """
        解析 GIS 文件

        Args:
            file_path: 文件路径
            file_type: 文件类型（可选，自动检测）

        Returns:
            ParseResult 对象
        """
        if not os.path.exists(file_path):
            return ParseResult(
                geojson={},
                error=f"文件不存在: {file_path}",
                success=False,
                source_file=file_path,
            )

        if file_type is None:
            file_type = self.detect_file_type(file_path)

        if file_type is None:
            return ParseResult(
                geojson={},
                error=f"无法识别文件类型: {file_path}",
                success=False,
                source_file=file_path,
            )

        parsers = {
            'geojson': self._parse_geojson,
            'shapefile': self._parse_shapefile,
            'kml': self._parse_kml,
            'kmz': self._parse_kmz,
            'geotiff': self._parse_geotiff,
        }

        parser_func = parsers.get(file_type)
        if parser_func is None:
            return ParseResult(
                geojson={},
                error=f"不支持的文件类型: {file_type}",
                success=False,
                source_file=file_path,
                file_type=file_type,
            )

        try:
            result = parser_func(file_path)
            result.file_type = file_type
            result.source_file = file_path
            logger.info(f"[GISParser] 解析成功: {file_path}, 类型: {file_type}, 特征数: {result.feature_count}")
            return result
        except Exception as e:
            logger.error(f"[GISParser] 解析失败: {file_path}, 错误: {e}")
            return ParseResult(
                geojson={},
                error=str(e),
                success=False,
                source_file=file_path,
                file_type=file_type,
            )

    def _parse_geojson(self, file_path: str) -> ParseResult:
        """解析 GeoJSON 文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 验证 GeoJSON 结构
        if data.get('type') not in ['FeatureCollection', 'Feature', 'GeometryCollection']:
            # 尝试包装为 FeatureCollection
            if 'coordinates' in data:
                data = {
                    'type': 'FeatureCollection',
                    'features': [{
                        'type': 'Feature',
                        'geometry': data,
                        'properties': {}
                    }]
                }

        # 统计特征数
        feature_count = 0
        properties = set()

        if data.get('type') == 'FeatureCollection':
            features = data.get('features', [])
            feature_count = len(features)
            for feat in features:
                if 'properties' in feat and feat['properties']:
                    properties.update(feat['properties'].keys())
        elif data.get('type') == 'Feature':
            feature_count = 1
            if 'properties' in data and data['properties']:
                properties.update(data['properties'].keys())

        return ParseResult(
            geojson=data,
            properties=list(properties),
            crs="EPSG:4326",  # GeoJSON 默认 WGS84
            feature_count=feature_count,
            success=True,
        )

    def _parse_shapefile(self, file_path: str) -> ParseResult:
        """解析 Shapefile（需要 geopandas）"""
        if not self._has_geopandas:
            return ParseResult(
                geojson={},
                error="需要安装 geopandas 才能解析 Shapefile",
                success=False,
            )

        import geopandas as gpd

        # 检查必需文件
        shp_dir = Path(file_path).parent
        shp_base = Path(file_path).stem
        required_files = [f"{shp_base}.shp", f"{shp_base}.dbf", f"{shp_base}.prj"]
        missing = [f for f in required_files if not (shp_dir / f).exists()]
        if missing:
            return ParseResult(
                geojson={},
                error=f"Shapefile 缺少必需文件: {missing}",
                success=False,
            )

        # 读取 Shapefile
        gdf = gpd.read_file(file_path)

        # 坐标转换：如果非 WGS84，转换为 WGS84
        if gdf.crs and gdf.crs != 'EPSG:4326':
            logger.info(f"[GISParser] 坐标转换: {gdf.crs} -> EPSG:4326")
            gdf = gdf.to_crs('EPSG:4326')

        # 转换为 GeoJSON
        geojson = json.loads(gdf.to_json())

        # 提取属性字段
        properties = [col for col in gdf.columns if col != 'geometry']

        return ParseResult(
            geojson=geojson,
            properties=properties,
            crs="EPSG:4326",
            feature_count=len(gdf),
            success=True,
        )

    def _parse_kml(self, file_path: str) -> ParseResult:
        """解析 KML 文件（需要 fastkml）"""
        if not self._has_fastkml:
            return ParseResult(
                geojson={},
                error="需要安装 fastkml 才能解析 KML",
                success=False,
            )

        from fastkml import kml

        with open(file_path, 'r', encoding='utf-8') as f:
            kml_doc = kml.KML()
            kml_doc.parse(f.read())

        # 提取所有 Placemark
        features = []
        properties = set()

        def extract_placemarks(doc, features, properties):
            for feature in doc.features:
                if hasattr(feature, 'features'):
                    extract_placemarks(feature, features, properties)
                elif hasattr(feature, 'geometry'):
                    geom = feature.geometry
                    if geom:
                        # 转换几何为 GeoJSON 格式
                        geojson_geom = self._kml_geometry_to_geojson(geom)
                        if geojson_geom:
                            feat_props = {}
                            if hasattr(feature, 'name') and feature.name:
                                feat_props['name'] = feature.name
                            if hasattr(feature, 'description') and feature.description:
                                feat_props['description'] = feature.description
                            if hasattr(feature, 'extended_data') and feature.extended_data:
                                for ed in feature.extended_data:
                                    feat_props[ed.name] = ed.value
                            properties.update(feat_props.keys())

                            features.append({
                                'type': 'Feature',
                                'geometry': geojson_geom,
                                'properties': feat_props,
                            })

        extract_placemarks(kml_doc, features, properties)

        geojson = {
            'type': 'FeatureCollection',
            'features': features,
        }

        return ParseResult(
            geojson=geojson,
            properties=list(properties),
            crs="EPSG:4326",
            feature_count=len(features),
            success=True,
        )

    def _parse_kmz(self, file_path: str) -> ParseResult:
        """解析 KMZ 文件（压缩的 KML）"""
        import zipfile

        with zipfile.ZipFile(file_path, 'r') as zf:
            # 找到 KML 文件
            kml_files = [f for f in zf.namelist() if f.endswith('.kml')]
            if not kml_files:
                return ParseResult(
                    geojson={},
                    error="KMZ 文件中未找到 KML",
                    success=False,
                )

            # 提取并解析第一个 KML（使用跨平台临时目录）
            with zf.open(kml_files[0]) as kml_file:
                with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as temp_f:
                    temp_f.write(kml_file.read())
                    temp_path = temp_f.name

                try:
                    result = self._parse_kml(temp_path)
                finally:
                    os.remove(temp_path)
                return result

    def _parse_geotiff(self, file_path: str) -> ParseResult:
        """解析 GeoTIFF 文件（需要 rasterio）"""
        if not self._has_rasterio:
            return ParseResult(
                geojson={},
                error="需要安装 rasterio 才能解析 GeoTIFF",
                success=False,
            )

        import rasterio
        from rasterio.features import shapes

        with rasterio.open(file_path) as src:
            # 获取元数据
            meta = {
                'crs': str(src.crs) if src.crs else 'unknown',
                'bounds': src.bounds,
                'width': src.width,
                'height': src.height,
                'count': src.count,
            }

            # 获取边界框作为 GeoJSON Polygon
            bounds = src.bounds
            bbox_geojson = {
                'type': 'Polygon',
                'coordinates': [[
                    [bounds.left, bounds.bottom],
                    [bounds.right, bounds.bottom],
                    [bounds.right, bounds.top],
                    [bounds.left, bounds.top],
                    [bounds.left, bounds.bottom],
                ]]
            }

            # 如果有分类数据，提取为矢量
            features = []
            if src.count > 0:
                band = src.read(1)
                mask = band != src.nodata if src.nodata is not None else None

                for geom, value in shapes(band, mask=mask, transform=src.transform):
                    if src.crs and src.crs != 'EPSG:4326':
                        # 需要坐标转换
                        import pyproj
                        transformer = pyproj.Transformer.from_crs(
                            src.crs, 'EPSG:4326', always_xy=True
                        )
                        coords = self._transform_coords(geom['coordinates'], transformer)
                        geom['coordinates'] = coords

                    features.append({
                        'type': 'Feature',
                        'geometry': geom,
                        'properties': {'value': value},
                    })

            # 如果没有提取到特征，使用边界框
            if not features:
                features = [{
                    'type': 'Feature',
                    'geometry': bbox_geojson,
                    'properties': {'type': 'extent', **meta},
                }]

            geojson = {
                'type': 'FeatureCollection',
                'features': features,
            }

            return ParseResult(
                geojson=geojson,
                properties=['value', 'type'] + list(meta.keys()),
                crs="EPSG:4326",
                feature_count=len(features),
                success=True,
            )

    def _kml_geometry_to_geojson(self, kml_geom) -> Optional[Dict]:
        """将 KML 几何转换为 GeoJSON 格式"""
        from fastkml.geometry import Point, LineString, Polygon, MultiGeometry

        if isinstance(kml_geom, Point):
            coords = kml_geom.coordinates
            return {
                'type': 'Point',
                'coordinates': [coords[0], coords[1]],
            }
        elif isinstance(kml_geom, LineString):
            coords = list(kml_geom.coordinates)
            return {
                'type': 'LineString',
                'coordinates': [[c[0], c[1]] for c in coords],
            }
        elif isinstance(kml_geom, Polygon):
            exterior = list(kml_geom.exterior.coords)
            interiors = [list(r.coords) for r in kml_geom.interiors] if kml_geom.interiors else []
            return {
                'type': 'Polygon',
                'coordinates': [
                    [[c[0], c[1]] for c in exterior],
                    *[[[c[0], c[1]] for c in r] for r in interiors]
                ],
            }
        elif isinstance(kml_geom, MultiGeometry):
            geometries = [self._kml_geometry_to_geojson(g) for g in kml_geom.geoms]
            return {
                'type': 'GeometryCollection',
                'geometries': geometries,
            }
        else:
            return None

    def _transform_coords(self, coords, transformer) -> Any:
        """递归转换坐标"""
        if isinstance(coords[0], (int, float)):
            return list(transformer.transform(coords[0], coords[1]))
        else:
            return [self._transform_coords(c, transformer) for c in coords]

    def infer_data_type(self, geojson: Dict[str, Any]) -> str:
        """
        智能推断数据类型

        根据属性字段推断数据类型（boundary/water/road/residential/custom）

        Args:
            geojson: GeoJSON 数据

        Returns:
            数据类型字符串
        """
        features = geojson.get('features', [])
        if not features:
            return 'custom'

        # 检查第一个特征的属性
        first_feature = features[0]
        props = first_feature.get('properties', {})

        # 根据属性字段推断
        prop_keys = set(props.keys())
        prop_values = {k: v for k, v in props.items() if isinstance(v, str)}

        # 边界数据特征
        if any(k in prop_keys for k in ['行政代码', 'boundary_type', '行政级别', '行政区划']):
            return 'boundary'
        if any(v in prop_values.values() for v in ['行政边界', '规划范围', '村界']):
            return 'boundary'

        # 水系数据特征
        if any(k in prop_keys for k in ['水系名称', 'water_type', '河流名称', '湖泊名称']):
            return 'water'
        if any(v in prop_values.values() for v in ['河流', '湖泊', '水库', '水系']):
            return 'water'

        # 道路数据特征
        if any(k in prop_keys for k in ['道路名称', 'road_level', '道路等级', '路名']):
            return 'road'
        if any(v in prop_values.values() for v in ['道路', '公路', '村道', '省道', '国道']):
            return 'road'

        # 居民点数据特征
        if any(k in prop_keys for k in ['居民点', 'population', '人口', '户数']):
            return 'residential'
        if any(v in prop_values.values() for v in ['居民点', '居住区', '村庄', '聚落']):
            return 'residential'

        # POI 设施特征
        if any(k in prop_keys for k in ['设施类型', 'facility_type', 'POI类型']):
            return 'poi'

        return 'custom'


def parse_gis_file(file_path: str) -> ParseResult:
    """
    便捷函数：解析 GIS 文件

    Args:
        file_path: 文件路径

    Returns:
        ParseResult 对象
    """
    parser = GISDataParser()
    return parser.parse(file_path)


__all__ = [
    'GISDataParser',
    'ParseResult',
    'parse_gis_file',
]