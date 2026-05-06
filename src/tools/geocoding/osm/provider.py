"""OpenStreetMap 数据提供者

使用 OSMnx 库获取道路网络数据，补充天地图 WFS 仅提供县级以上道路的限制。

优势：
- 全级别道路覆盖（含村级道路）
- WGS84 坐标系（无需转换）
- 免费 API（无需 Key）
- 社区维护，更新频繁
"""

import json
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import asdict

try:
    import osmnx as ox
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False

from .types import OSMResult, OSMRoadFeature
from .constants import HIGHWAY_CLASSES, VILLAGE_RELEVANT_HIGHWAYS, NETWORK_TYPES
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OSMProvider:
    """OpenStreetMap 数据提供者"""

    def __init__(self, use_cache: bool = True):
        """初始化 OSM Provider

        Args:
            use_cache: 是否使用 OSMnx 缓存（默认启用）
        """
        if not OSMNX_AVAILABLE:
            logger.warning("[OSMProvider] osmnx 库未安装，请运行: pip install osmnx")

        # 配置 OSMnx
        if use_cache and OSMNX_AVAILABLE:
            ox.settings.use_cache = True
            ox.settings.log_console = False

        self._cache_folder = ".osmnx_cache"

    def is_available(self) -> bool:
        """检查 OSMnx 是否可用"""
        return OSMNX_AVAILABLE

    def get_road_network(
        self,
        bbox: Tuple[float, float, float, float],
        network_type: str = "drive",
        simplify: bool = True,
        retain_all: bool = False,
    ) -> OSMResult:
        """获取道路网络数据

        Args:
            bbox: 边界框 (south, west, north, east) WGS84
                  注意：OSMnx 使用 (north, south, east, west) 顺序
            network_type: 网络类型
                - "all": 所有道路
                - "drive": 机动车道路
                - "bike": 自行车道
                - "walk": 步行道路
            simplify: 是否简化拓扑（去除中间节点）
            retain_all: 是否保留非连通道路

        Returns:
            OSMResult 包含 GeoJSON FeatureCollection
        """
        if not OSMNX_AVAILABLE:
            return OSMResult(
                success=False,
                error="osmnx 库未安装，请运行: pip install osmnx",
                metadata={"bbox": bbox},
            )

        south, west, north, east = bbox

        # OSMnx 2.x: bbox 格式为 (left, bottom, right, top) = (west, south, east, north)
        # 所有参数都是 keyword-only
        try:
            logger.info(f"[OSMProvider] 获取道路网络: bbox={bbox}, type={network_type}")

            G = ox.graph_from_bbox(
                bbox=(west, south, east, north),
                network_type=network_type,
                simplify=simplify,
                retain_all=retain_all,
                truncate_by_edge=True,  # 按边界截断
            )

            # 转换为 GeoDataFrame
            nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

            # 统计道路类型
            highway_stats = self._count_highway_types(edges_gdf)

            # 构建 GeoJSON FeatureCollection
            features = []
            for idx, edge in edges_gdf.iterrows():
                feature = self._edge_to_geojson_feature(idx, edge)
                features.append(feature)

            geojson = {
                "type": "FeatureCollection",
                "features": features,
                "metadata": {
                    "source": "osm",
                    "bbox": bbox,
                    "network_type": network_type,
                    "feature_count": len(features),
                    "highway_stats": highway_stats,
                    "village_relevant_count": sum(
                        highway_stats.get(h, 0) for h in VILLAGE_RELEVANT_HIGHWAYS
                    ),
                },
            }

            logger.info(
                f"[OSMProvider] 成功获取 {len(features)} 条道路, "
                f"村级相关道路 {geojson['metadata']['village_relevant_count']} 条"
            )

            return OSMResult(
                success=True,
                data=geojson,
                metadata={
                    "bbox": bbox,
                    "network_type": network_type,
                    "total_edges": len(edges_gdf),
                    "total_nodes": len(nodes_gdf),
                },
                total_features=len(features),
                highway_stats=highway_stats,
            )

        except Exception as e:
            logger.error(f"[OSMProvider] 获取道路网络失败: {e}")
            return OSMResult(
                success=False,
                error=str(e),
                metadata={"bbox": bbox, "network_type": network_type},
            )

    def get_road_network_by_place(
        self,
        place_name: str,
        network_type: str = "drive",
        which_result: int = 1,
    ) -> OSMResult:
        """通过地名获取道路网络

        Args:
            place_name: 地名（如 "金田村, 平远县, 梅州市, 广东省"）
            network_type: 网络类型
            which_result: Nominatim 搜索结果索引

        Returns:
            OSMResult 包含 GeoJSON FeatureCollection
        """
        if not OSMNX_AVAILABLE:
            return OSMResult(
                success=False,
                error="osmnx 库未安装",
                metadata={"place_name": place_name},
            )

        try:
            logger.info(f"[OSMProvider] 通过地名获取道路: {place_name}")

            G = ox.graph_from_place(
                place_name,
                network_type=network_type,
                which_result=which_result,
                simplify=True,
            )

            nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

            # 获取边界
            bbox = edges_gdf.total_bounds  # (minx, miny, maxx, maxy)

            # 统计和构建 GeoJSON
            highway_stats = self._count_highway_types(edges_gdf)
            features = [
                self._edge_to_geojson_feature(idx, edge)
                for idx, edge in edges_gdf.iterrows()
            ]

            geojson = {
                "type": "FeatureCollection",
                "features": features,
                "metadata": {
                    "source": "osm",
                    "place_name": place_name,
                    "network_type": network_type,
                    "feature_count": len(features),
                    "highway_stats": highway_stats,
                    "bbox": [bbox[1], bbox[0], bbox[3], bbox[2]],  # (south, west, north, east)
                },
            }

            return OSMResult(
                success=True,
                data=geojson,
                metadata={"place_name": place_name, "bbox": bbox},
                total_features=len(features),
                highway_stats=highway_stats,
            )

        except Exception as e:
            logger.error(f"[OSMProvider] 通过地名获取道路失败: {e}")
            return OSMResult(
                success=False,
                error=str(e),
                metadata={"place_name": place_name},
            )

    def get_roads_by_polygon(
        self,
        polygon_geojson: Dict[str, Any],
        network_type: str = "drive",
    ) -> OSMResult:
        """通过多边形边界获取道路网络

        Args:
            polygon_geojson: GeoJSON Polygon 或 MultiPolygon
            network_type: 网络类型

        Returns:
            OSMResult 包含 GeoJSON FeatureCollection
        """
        if not OSMNX_AVAILABLE:
            return OSMResult(
                success=False,
                error="osmnx 库未安装",
            )

        try:
            from shapely.geometry import shape

            polygon = shape(polygon_geojson)

            logger.info(f"[OSMProvider] 通过多边形获取道路网络")

            G = ox.graph_from_polygon(
                polygon,
                network_type=network_type,
                simplify=True,
                retain_all=True,  # 保留所有道路
            )

            nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

            highway_stats = self._count_highway_types(edges_gdf)
            features = [
                self._edge_to_geojson_feature(idx, edge)
                for idx, edge in edges_gdf.iterrows()
            ]

            geojson = {
                "type": "FeatureCollection",
                "features": features,
                "metadata": {
                    "source": "osm",
                    "network_type": network_type,
                    "feature_count": len(features),
                    "highway_stats": highway_stats,
                    "village_relevant_count": sum(
                        highway_stats.get(h, 0) for h in VILLAGE_RELEVANT_HIGHWAYS
                    ),
                },
            }

            return OSMResult(
                success=True,
                data=geojson,
                total_features=len(features),
                highway_stats=highway_stats,
            )

        except Exception as e:
            logger.error(f"[OSMProvider] 通过多边形获取道路失败: {e}")
            return OSMResult(
                success=False,
                error=str(e),
            )

    def _count_highway_types(self, edges_gdf) -> Dict[str, int]:
        """统计道路类型分布

        Args:
            edges_gdf: OSMnx edges GeoDataFrame

        Returns:
            各 highway 类型的数量统计
        """
        highway_stats = {}

        for highway_value in edges_gdf["highway"]:
            # 处理列表类型（部分道路有多种类型）
            if isinstance(highway_value, list):
                primary_type = highway_value[0]
            else:
                primary_type = highway_value

            highway_stats[primary_type] = highway_stats.get(primary_type, 0) + 1

        return highway_stats

    def _edge_to_geojson_feature(
        self, idx: Tuple[int, int, int], edge: Any
    ) -> Dict[str, Any]:
        """将 OSMnx edge 转换为 GeoJSON Feature

        Args:
            idx: (u, v, key) 节点索引
            edge: edge 数据行

        Returns:
            GeoJSON Feature dict
        """
        highway_value = edge.get("highway", "unknown")
        if isinstance(highway_value, list):
            highway_value = highway_value[0]

        # 处理 name 字段（可能有 NaN 值）
        import math
        name = edge.get("name", "")
        if isinstance(name, list):
            name = name[0] if name else ""
        # 处理 NaN 值
        if isinstance(name, float) and math.isnan(name):
            name = ""

        # OSM ID（edge key 由 u, v, key 组成）
        osm_id = idx[0]  # source node OSM ID

        # 几何数据
        geometry = None
        if "geometry" in edge and edge["geometry"] is not None:
            geometry = edge["geometry"].__geo_interface__

        return {
            "type": "Feature",
            "properties": {
                "highway": highway_value,
                "highway_desc": HIGHWAY_CLASSES.get(highway_value, highway_value),
                "name": name,
                "length": float(edge.get("length", 0)),
                "osm_id": osm_id,
                "source": "osm",
            },
            "geometry": geometry,
        }

    def save_geojson(self, result: OSMResult, filepath: str) -> bool:
        """保存 GeoJSON 到文件

        Args:
            result: OSM 查询结果
            filepath: 输出文件路径

        Returns:
            是否成功保存
        """
        if not result.success or not result.data:
            logger.warning(f"[OSMProvider] 无法保存失败的结果")
            return False

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result.data, f, ensure_ascii=False, indent=2)
            logger.info(f"[OSMProvider] GeoJSON 已保存: {filepath}")
            return True
        except Exception as e:
            logger.error(f"[OSMProvider] 保存 GeoJSON 失败: {e}")
            return False