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
import io
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union, BinaryIO
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

    def detect_file_type_from_name(self, filename: str) -> Optional[str]:
        """
        根据文件名检测文件类型（用于字节流解析）

        Args:
            filename: 文件名（包含扩展名）

        Returns:
            文件类型键名，无法识别返回 None
        """
        ext = Path(filename).suffix.lower()
        for format_name, extensions in self.SUPPORTED_FORMATS.items():
            if ext in extensions:
                return format_name
        return None

    def parse_from_bytes(
        self,
        content: bytes,
        filename: str,
        file_type: Optional[str] = None
    ) -> ParseResult:
        """
        从字节流解析 GIS 文件（无需保存到磁盘）

        适用于 API 上传场景，避免临时文件持久化。
        GeoJSON 直接 JSON 解析，其他格式使用临时文件。

        Args:
            content: 文件内容字节流
            filename: 文件名（用于检测文件类型）
            file_type: 文件类型（可选，自动检测）

        Returns:
            ParseResult 对象
        """
        if file_type is None:
            file_type = self.detect_file_type_from_name(filename)

        if file_type is None:
            return ParseResult(
                geojson={},
                error=f"无法识别文件类型: {filename}",
                success=False,
                source_file=filename,
            )

        # GeoJSON - 直接解析（无需临时文件）
        if file_type == 'geojson':
            try:
                data = json.loads(content.decode('utf-8'))
                result = self._parse_geojson_data(data)
                result.file_type = file_type
                result.source_file = filename
                logger.info(f"[GISParser] 字节流解析成功: {filename}, 类型: {file_type}, 特征数: {result.feature_count}")
                return result
            except Exception as e:
                logger.error(f"[GISParser] GeoJSON 字节流解析失败: {e}")
                return ParseResult(
                    geojson={},
                    error=str(e),
                    success=False,
                    source_file=filename,
                    file_type=file_type,
                )

        # Shapefile - 需要临时文件和辅助文件
        if file_type == 'shapefile':
            return self._parse_shapefile_from_bytes(content, filename)

        # KML/KMZ/GeoTIFF - 使用临时文件
        parsers_from_bytes = {
            'kml': self._parse_kml_from_bytes,
            'kmz': self._parse_kmz_from_bytes,
            'geotiff': self._parse_geotiff_from_bytes,
        }

        parser_func = parsers_from_bytes.get(file_type)
        if parser_func is None:
            return ParseResult(
                geojson={},
                error=f"字节流解析不支持: {file_type}",
                success=False,
                source_file=filename,
                file_type=file_type,
            )

        try:
            result = parser_func(content, filename)
            result.file_type = file_type
            result.source_file = filename
            logger.info(f"[GISParser] 字节流解析成功: {filename}, 类型: {file_type}, 特征数: {result.feature_count}")
            return result
        except Exception as e:
            logger.error(f"[GISParser] 字节流解析失败: {filename}, 错误: {e}")
            return ParseResult(
                geojson={},
                error=str(e),
                success=False,
                source_file=filename,
                file_type=file_type,
            )

    def _parse_geojson_data(self, data: Dict[str, Any]) -> ParseResult:
        """解析 GeoJSON 数据（已解码为 dict）"""
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
            crs="EPSG:4326",
            feature_count=feature_count,
            success=True,
        )

    def _parse_shapefile_from_bytes(self, content: bytes, filename: str) -> ParseResult:
        """
        从字节流解析 Shapefile

        注意：Shapefile 需要多个文件（.shp, .dbf, .shx, .prj），
        单文件上传仅支持 .shp + .dbf 组合或 ZIP 打包的完整 Shapefile。

        Args:
            content: 文件字节流
            filename: 文件名

        Returns:
            ParseResult
        """
        if not self._has_geopandas:
            return ParseResult(
                geojson={},
                error="需要安装 geopandas 才能解析 Shapefile",
                success=False,
            )

        import geopandas as gpd

        # 检查是否是 ZIP 文件（包含完整 Shapefile）
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
                shp_files = [f for f in zf.namelist() if f.endswith('.shp')]
                if shp_files:
                    # 提取到临时目录
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        zf.extractall(tmp_dir)
                        shp_path = os.path.join(tmp_dir, shp_files[0])

                        # 读取 Shapefile
                        gdf = gpd.read_file(shp_path)

                        # 坐标转换
                        if gdf.crs and gdf.crs != 'EPSG:4326':
                            logger.info(f"[GISParser] 坐标转换: {gdf.crs} -> EPSG:4326")
                            gdf = gdf.to_crs('EPSG:4326')

                        geojson = json.loads(gdf.to_json())
                        properties = [col for col in gdf.columns if col != 'geometry']

                        return ParseResult(
                            geojson=geojson,
                            properties=properties,
                            crs="EPSG:4326",
                            feature_count=len(gdf),
                            success=True,
                        )
        except zipfile.BadZipFile:
            pass  # 不是 ZIP 文件，继续尝试单 .shp 文件

        # 单 .shp 文件处理（需要提示用户上传完整文件集）
        return ParseResult(
            geojson={},
            error="Shapefile 需要完整的文件集（.shp + .dbf + .prj），请将所有文件打包为 ZIP 后上传",
            success=False,
            source_file=filename,
        )

    def _parse_kml_from_bytes(self, content: bytes, filename: str) -> ParseResult:
        """从字节流解析 KML 文件"""
        if not self._has_fastkml:
            return ParseResult(
                geojson={},
                error="需要安装 fastkml 才能解析 KML",
                success=False,
            )

        from fastkml import kml

        # 解码内容
        try:
            kml_text = content.decode('utf-8')
        except UnicodeDecodeError:
            kml_text = content.decode('latin-1')

        kml_doc = kml.KML()
        kml_doc.parse(kml_text)

        # 提取 Placemark
        features = []
        properties = set()

        def extract_placemarks(doc, features, properties):
            for feature in doc.features:
                if hasattr(feature, 'features'):
                    extract_placemarks(feature, features, properties)
                elif hasattr(feature, 'geometry'):
                    geom = feature.geometry
                    if geom:
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

    def _parse_kmz_from_bytes(self, content: bytes, filename: str) -> ParseResult:
        """从字节流解析 KMZ 文件"""
        import zipfile

        with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
            kml_files = [f for f in zf.namelist() if f.endswith('.kml')]
            if not kml_files:
                return ParseResult(
                    geojson={},
                    error="KMZ 文件中未找到 KML",
                    success=False,
                )

            # 读取第一个 KML 文件
            with zf.open(kml_files[0]) as kml_file:
                kml_content = kml_file.read()
                return self._parse_kml_from_bytes(kml_content, filename)

    def _parse_geotiff_from_bytes(self, content: bytes, filename: str) -> ParseResult:
        """从字节流解析 GeoTIFF 文件（使用临时文件）"""
        if not self._has_rasterio:
            return ParseResult(
                geojson={},
                error="需要安装 rasterio 才能解析 GeoTIFF",
                success=False,
            )

        import rasterio
        from rasterio.features import shapes

        # 写入临时文件
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with rasterio.open(tmp_path) as src:
                # 获取元数据
                meta = {
                    'crs': str(src.crs) if src.crs else 'unknown',
                    'bounds': src.bounds,
                    'width': src.width,
                    'height': src.height,
                    'count': src.count,
                }

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

                features = []
                if src.count > 0:
                    band = src.read(1)
                    mask = band != src.nodata if src.nodata is not None else None

                    for geom, value in shapes(band, mask=mask, transform=src.transform):
                        if src.crs and src.crs != 'EPSG:4326':
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
        finally:
            os.remove(tmp_path)

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


def parse_gis_from_bytes(content: bytes, filename: str) -> ParseResult:
    """
    便捷函数：从字节流解析 GIS 文件

    Args:
        content: 文件内容字节流
        filename: 文件名（用于检测文件类型）

    Returns:
        ParseResult 对象
    """
    parser = GISDataParser()
    return parser.parse_from_bytes(content, filename)


__all__ = [
    'GISDataParser',
    'ParseResult',
    'parse_gis_file',
    'parse_gis_from_bytes',
]