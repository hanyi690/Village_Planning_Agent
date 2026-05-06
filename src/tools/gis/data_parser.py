"""
GIS 数据解析模块

统一解析多种 GIS 格式，输出标准 GeoJSON。
支持 GeoJSON、Shapefile、KML/KMZ、GeoTIFF、GDB 等格式。

依赖库:
- geopandas: Shapefile/GDB 解析和坐标转换
- fastkml: KML 解析
- rasterio: GeoTIFF 解析（可选）
"""

import json
import os
import tempfile
import logging
import io
import pandas as pd
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
        'gdb': ['.gdb'],
        'kml': ['.kml'],
        'kmz': ['.kmz'],
        'geotiff': ['.tif', '.tiff'],
    }

    # 图层名称关键词映射 - 类常量，避免每次调用都创建
    # 与前端 DataUpload.tsx DATA_TYPE_KEYWORDS 保持同步
    LAYER_TYPE_KEYWORDS = {
        'boundary': ['边界', '行政区划', '行政村', '村界', '规划范围', 'boundary', '行政代码', 'boundary_type', '行政级别', 'XZDM', 'XZMC', '行政边界'],
        'landuse': ['土地利用', '用地', '图斑', '地类', '现状', '规划', 'landuse', '地类代码', 'DLBM', '地类名称', 'DLMC', '用地性质', '耕地', '林地', '建设用地', '农用地'],
        'road': ['道路', '路网', '交通', 'road', '公路', '道路名称', 'road_level', '道路等级', '路名', 'RN', '道路编码', '村道', '省道', '国道', '高速公路', '乡道'],
        'water': ['水系', '河流', '水域', 'water', 'HYD', '水系名称', 'water_type', '河流名称', '湖泊名称', 'HYD_NM', '湖泊', '水库', '水渠', '池塘'],
        'residential': ['居民点', '居住', '村庄', 'residential', '住宅', 'population', '人口', '户数', '户数_人', '常住人口', '居住区', '聚落', '居民地'],
        'poi': ['设施', 'POI', '公共', '服务', 'poi', 'facility', '设施类型', 'facility_type', 'POI类型', '设施名称', '服务类型', '学校', '医院', '卫生院', '文化活动', '养老服务', '公共设施'],
        'protection_zone': ['红线', '保护', '农田', '生态', '历史', 'protection', '保护级别', '红线类型', '保护类型', 'protection_level', '农田保护', '生态保护', '基本农田', '生态红线', '历史保护', '永久农田', '保护红线'],
        'geological_hazard': ['地质', '灾害', '隐患', '滑坡', '崩塌', 'geological', '灾害类型', '隐患等级', '地质类型', 'hazard_type', '灾害名称', '泥石流', '地面塌陷', '地质灾害', '隐患点'],
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

        # KML/KMZ/GeoTIFF/GDB - 使用临时文件
        parsers_from_bytes = {
            'kml': self._parse_kml_from_bytes,
            'kmz': self._parse_kmz_from_bytes,
            'geotiff': self._parse_geotiff_from_bytes,
            'gdb': self._parse_gdb_from_bytes,
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
            'gdb': self._parse_gdb,
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

    def infer_data_type(self, geojson: Dict[str, Any], layer_name: Optional[str] = None) -> str:
        """
        智能推断数据类型

        根据属性字段和图层名称推断数据类型
        支持类型: boundary/water/road/residential/poi/landuse/protection_zone/geological_hazard/custom

        Args:
            geojson: GeoJSON 数据
            layer_name: 图层名称（可选，用于辅助推断）

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

        # 首先根据图层名称推断（使用类常量）
        if layer_name:
            for data_type, keywords in self.LAYER_TYPE_KEYWORDS.items():
                if any(kw.lower() in layer_name.lower() for kw in keywords):
                    logger.debug(f"[GISParser] 根据图层名称 '{layer_name}' 推断类型: {data_type}")
                    return data_type

        # 边界数据特征
        boundary_keys = ['行政代码', 'boundary_type', '行政级别', '行政区划', 'XZDM', 'XZMC']
        boundary_values = ['行政边界', '规划范围', '村界', '行政村']
        if any(k in prop_keys for k in boundary_keys):
            return 'boundary'
        if any(v in prop_values.values() for v in boundary_values):
            return 'boundary'

        # 土地利用数据特征
        landuse_keys = ['地类代码', 'DLBM', '地类名称', 'DLMC', '用地性质', '土地利用', 'landuse_type']
        landuse_values = ['耕地', '林地', '建设用地', '农用地', '未利用地']
        if any(k in prop_keys for k in landuse_keys):
            return 'landuse'
        if any(v in prop_values.values() for v in landuse_values):
            return 'landuse'

        # 保护红线数据特征
        protection_keys = ['保护级别', '红线类型', '保护类型', 'protection_level', '农田保护', '生态保护']
        protection_values = ['基本农田', '生态红线', '历史保护', '永久农田', '保护红线']
        if any(k in prop_keys for k in protection_keys):
            return 'protection_zone'
        if any(v in prop_values.values() for v in protection_values):
            return 'protection_zone'

        # 地质灾害数据特征
        hazard_keys = ['灾害类型', '隐患等级', '地质类型', 'hazard_type', '灾害名称']
        hazard_values = ['滑坡', '崩塌', '泥石流', '地面塌陷', '地质灾害', '隐患点']
        if any(k in prop_keys for k in hazard_keys):
            return 'geological_hazard'
        if any(v in prop_values.values() for v in hazard_values):
            return 'geological_hazard'

        # 水系数据特征
        water_keys = ['水系名称', 'water_type', '河流名称', '湖泊名称', 'HYD_NM']
        water_values = ['河流', '湖泊', '水库', '水系', '水渠', '池塘']
        if any(k in prop_keys for k in water_keys):
            return 'water'
        if any(v in prop_values.values() for v in water_values):
            return 'water'

        # 道路数据特征
        road_keys = ['道路名称', 'road_level', '道路等级', '路名', 'RN', '道路编码']
        road_values = ['道路', '公路', '村道', '省道', '国道', '高速公路', '乡道']
        if any(k in prop_keys for k in road_keys):
            return 'road'
        if any(v in prop_values.values() for v in road_values):
            return 'road'

        # 居民点数据特征
        residential_keys = ['居民点', 'population', '人口', '户数', '户数_人', '常住人口']
        residential_values = ['居民点', '居住区', '村庄', '聚落', '居民地']
        if any(k in prop_keys for k in residential_keys):
            return 'residential'
        if any(v in prop_values.values() for v in residential_values):
            return 'residential'

        # POI 设施特征
        poi_keys = ['设施类型', 'facility_type', 'POI类型', '设施名称', '服务类型']
        poi_values = ['学校', '医院', '卫生院', '文化活动', '养老服务', '公共设施']
        if any(k in prop_keys for k in poi_keys):
            return 'poi'
        if any(v in prop_values.values() for v in poi_values):
            return 'poi'

        return 'custom'

    def _parse_gdb(self, gdb_path: str, layer_name: Optional[str] = None) -> ParseResult:
        """
        解析 ArcGIS File Geodatabase (.gdb) 目录

        Args:
            gdb_path: GDB 目录路径
            layer_name: 可选的图层名称，如果不指定则合并所有图层

        Returns:
            ParseResult
        """
        if not self._has_geopandas:
            return ParseResult(
                geojson={},
                error="需要安装 geopandas 才能解析 GDB",
                success=False,
            )

        import geopandas as gpd

        # 检查路径是否存在且是目录
        gdb_dir = Path(gdb_path)
        if not gdb_dir.exists():
            return ParseResult(
                geojson={},
                error=f"GDB 目录不存在: {gdb_path}",
                success=False,
            )
        if not gdb_dir.is_dir():
            return ParseResult(
                geojson={},
                error=f"GDB 路径不是目录: {gdb_path}",
                success=False,
            )

        try:
            # 获取所有图层列表
            layers = gpd.list_layers(gdb_path)
            if layers.empty:
                return ParseResult(
                    geojson={},
                    error=f"GDB 目录中没有图层: {gdb_path}",
                    success=False,
                )

            logger.info(f"[GISParser] GDB 图层列表: {layers['name'].tolist()}")

            # 选择图层
            if layer_name:
                # 指定图层
                target_layer = layers[layers['name'] == layer_name]
                if target_layer.empty:
                    available = layers['name'].tolist()
                    return ParseResult(
                        geojson={},
                        error=f"未找到图层 '{layer_name}'，可用图层: {available}",
                        success=False,
                    )
                gdf = gpd.read_file(gdb_path, layer=layer_name)
            else:
                # 合并所有图层（每个图层的属性可能不同）
                all_gdfs = []
                for layer_row in layers.itertuples():
                    layer_gdf = gpd.read_file(gdb_path, layer=layer_row.name)
                    # 添加图层名称属性
                    layer_gdf['_gdb_layer'] = layer_row.name
                    all_gdfs.append(layer_gdf)
                gdf = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True), crs=all_gdfs[0].crs)

            # 坐标转换
            if gdf.crs and gdf.crs != 'EPSG:4326':
                logger.info(f"[GISParser] GDB 坐标转换: {gdf.crs} -> EPSG:4326")
                gdf = gdf.to_crs('EPSG:4326')

            # 转换为 GeoJSON
            geojson = json.loads(gdf.to_json())
            properties = [col for col in gdf.columns if col != 'geometry']

            return ParseResult(
                geojson=geojson,
                properties=properties,
                crs="EPSG:4326",
                feature_count=len(gdf),
                success=True,
            )

        except Exception as e:
            logger.error(f"[GISParser] GDB 解析失败: {gdb_path}, 错误: {e}")
            return ParseResult(
                geojson={},
                error=f"GDB 解析失败: {str(e)}",
                success=False,
            )

    def _parse_gdb_from_bytes(self, content: bytes, filename: str) -> ParseResult:
        """
        从字节流解析 ZIP 打包的 GDB 目录

        Args:
            content: ZIP 文件字节流
            filename: 文件名

        Returns:
            ParseResult
        """
        if not self._has_geopandas:
            return ParseResult(
                geojson={},
                error="需要安装 geopandas 才能解析 GDB",
                success=False,
            )

        import geopandas as gpd
        import zipfile

        # 检查是否是 ZIP 文件
        try:
            with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
                # 检查 ZIP 内容是否包含 .gdb 目录
                gdb_dirs = [f for f in zf.namelist() if '.gdb/' in f or f.endswith('.gdb')]
                if not gdb_dirs:
                    return ParseResult(
                        geojson={},
                        error="ZIP 文件不包含 GDB 目录。GDB 上传需要将 .gdb 目录打包为 ZIP",
                        success=False,
                    )

                # 提取到临时目录
                with tempfile.TemporaryDirectory() as tmp_dir:
                    zf.extractall(tmp_dir)

                    # 直接从 ZIP 内容获取 .gdb 目录名（避免 os.walk）
                    first_entry = gdb_dirs[0]
                    if first_entry.endswith('.gdb'):
                        gdb_name = first_entry
                    else:
                        # 从路径中提取目录名（如 "data.gdb/file" -> "data.gdb"）
                        gdb_name = first_entry.split('/')[0]
                    gdb_path = os.path.join(tmp_dir, gdb_name)

                    if not os.path.isdir(gdb_path):
                        return ParseResult(
                            geojson={},
                            error="解压后未找到 .gdb 目录",
                            success=False,
                        )

                    # 使用 _parse_gdb 方法解析
                    result = self._parse_gdb(gdb_path)
                    result.source_file = filename
                    return result

        except zipfile.BadZipFile:
            return ParseResult(
                geojson={},
                error=f"无效的 ZIP 文件: {filename}",
                success=False,
            )
        except Exception as e:
            logger.error(f"[GISParser] GDB 字节流解析失败: {filename}, 错误: {e}")
            return ParseResult(
                geojson={},
                error=f"GDB 解析失败: {str(e)}",
                success=False,
            )

    def get_gdb_layers(self, gdb_path: str) -> List[str]:
        """
        获取 GDB 目录中的所有图层名称

        Args:
            gdb_path: GDB 目录路径

        Returns:
            图层名称列表
        """
        if not self._has_geopandas:
            return []

        import geopandas as gpd

        try:
            layers = gpd.list_layers(gdb_path)
            return layers['name'].tolist()
        except Exception as e:
            logger.error(f"[GISParser] 获取 GDB 图层列表失败: {e}")
            return []


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