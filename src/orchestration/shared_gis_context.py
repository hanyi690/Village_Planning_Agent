"""
共享 GIS 数据上下文

统一管理规划流程中的公共 GIS 数据，包括：
- village_name: 村名
- center: 中心点坐标
- bbox: 边界范围
- user_uploaded_data: 用户上传的 GIS 数据

数据优先级：用户上传 > 会话缓存 > API 自动获取

分层架构（新增）:
- Layer 0: 基础数据层 (boundary, water, road, residential)
- Layer 1: 分析数据层 (landuse_current, landuse_planned, hazard_points)
- Layer 2: 约束数据层 (protection_zones, construction_zone)

复用 GISDataFetcher 单例进行中心点计算，避免重复创建 TiandituProvider。
"""

from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass, field

from ..utils.logger import get_logger

logger = get_logger(__name__)

# 默认中心点（中国中部）
DEFAULT_CENTER = (116.4, 39.9)

# 支持的 GIS 数据类型（分层）
GIS_DATA_TYPES = ['boundary', 'water', 'road', 'residential', 'poi', 'landuse',
                  'protection_zone', 'geological_hazard', 'custom']

# 分层数据类型定义
LAYER_0_TYPES = ['boundary', 'water', 'road', 'residential', 'center']
LAYER_1_TYPES = ['landuse_current', 'landuse_planned', 'geological_hazard', 'poi']
LAYER_2_TYPES = ['farmland_protection', 'ecological_protection', 'historical_protection',
                 'construction_zone', 'hazard_buffer',
                 'three_zones_three_lines',  # 广东省天地图专题服务
                 'geological_hazard_points']


@dataclass
class SharedGISContext:
    """共享 GIS 数据上下文 - 统一管理公共 GIS 数据（分层架构）"""

    village_name: str
    buffer_km: float = 5.0

    # Layer 0: 基础数据层（优先级最高）
    _base_data: Dict[str, Any] = field(default_factory=dict, repr=False)
    _center: Optional[Tuple[float, float]] = field(default=None, repr=False)
    _bbox: Optional[Tuple[float, float, float, float]] = field(default=None, repr=False)

    # Layer 1: 分析数据层
    _analysis_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    # Layer 2: 约束数据层
    _constraint_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    # 用户上传的 GIS 数据: {data_type: geojson}
    _user_uploaded_data: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)

    # 数据来源追踪
    _data_sources: Dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def center(self) -> Tuple[float, float]:
        """获取中心点，带容错"""
        if self._center is None:
            self._center = self._compute_center()
        return self._center or DEFAULT_CENTER

    @property
    def center_raw(self) -> Optional[Tuple[float, float]]:
        """获取原始中心点（无默认值兜底）"""
        if self._center is None:
            self._center = self._compute_center()
        return self._center

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """获取边界范围"""
        if self._bbox is None:
            self._bbox = self._compute_bbox()
        return self._bbox

    def _compute_center(self) -> Optional[Tuple[float, float]]:
        """计算中心点 - 使用 GISDataFetcher 单例"""
        if not self.village_name:
            logger.warning("[SharedGISContext] village_name 为空，无法计算 center")
            return None

        try:
            from ..tools.core.gis_data_fetcher import get_fetcher
            fetcher = get_fetcher()  # 使用单例

            center, metadata = fetcher.get_village_center(self.village_name, buffer_km=self.buffer_km)

            if center:
                logger.info(f"[SharedGISContext] 定位成功: {self.village_name} -> {center}")
                return center

            logger.warning(f"[SharedGISContext] 无法定位 {self.village_name}，将使用默认中心点")
            return None

        except Exception as e:
            logger.error(f"[SharedGISContext] 定位异常: {e}")
            return None

    def _compute_bbox(self) -> Tuple[float, float, float, float]:
        """计算边界范围（基于 center 和 buffer_km）"""
        c = self.center
        buffer_deg = self.buffer_km / 111.0
        return (c[0] - buffer_deg, c[1] - buffer_deg,
                c[0] + buffer_deg, c[1] + buffer_deg)

    # ============================================
    # 用户上传数据管理
    # ============================================

    @property
    def user_uploaded_types(self) -> List[str]:
        """获取用户已上传的数据类型列表"""
        return list(self._user_uploaded_data.keys())

    @property
    def user_uploaded_data(self) -> Dict[str, Dict[str, Any]]:
        """获取所有用户上传的 GIS 数据"""
        return self._user_uploaded_data

    def set_user_data(self, data_type: str, geojson: Dict[str, Any]) -> None:
        """
        注入用户上传的 GIS 数据

        Args:
            data_type: 数据类型 (boundary/water/road/residential/poi/...)
            geojson: GeoJSON 数据
        """
        self._user_uploaded_data[data_type] = geojson
        feature_count = len(geojson.get('features', []))
        logger.info(f"[SharedGISContext] 用户数据注入: {data_type}, 特征数: {feature_count}")

        # 如果注入了边界数据，更新 center 和 bbox
        if data_type == 'boundary':
            self._update_center_from_boundary(geojson)

    def get_data_by_type(self, data_type: str) -> Optional[Dict[str, Any]]:
        """
        获取特定类型的 GIS 数据

        优先级：用户上传 > 会话缓存 > API 自动获取

        Args:
            data_type: 数据类型

        Returns:
            GeoJSON 数据或 None
        """
        # 优先返回用户上传数据
        if data_type in self._user_uploaded_data:
            logger.debug(f"[SharedGISContext] 返回用户上传数据: {data_type}")
            return self._user_uploaded_data[data_type]

        # 尝试从 GISDataManager 获取
        try:
            from ..tools.gis.data_manager import GISDataManager
            cached = GISDataManager.get_geojson(self.village_name, data_type)
            if cached:
                logger.debug(f"[SharedGISContext] 返回缓存数据: {data_type}")
                return cached
        except ImportError:
            pass

        return None

    def has_user_data(self, data_type: str) -> bool:
        """检查是否有用户上传数据"""
        return data_type in self._user_uploaded_data

    def clear_user_data(self, data_type: str) -> bool:
        """清除特定类型的用户数据"""
        if data_type in self._user_uploaded_data:
            del self._user_uploaded_data[data_type]
            logger.info(f"[SharedGISContext] 用户数据已清除: {data_type}")
            return True
        return False

    def clear_all_user_data(self) -> None:
        """清除所有用户数据"""
        self._user_uploaded_data.clear()
        logger.info(f"[SharedGISContext] 所有用户数据已清除")

    def _update_center_from_boundary(self, boundary_geojson: Dict[str, Any]) -> None:
        """
        从边界数据更新中心点

        Args:
            boundary_geojson: 边界 GeoJSON 数据
        """
        features = boundary_geojson.get('features', [])
        if not features:
            return

        # 计算所有坐标的平均值作为中心点
        all_coords = []
        for feature in features:
            geom = feature.get('geometry', {})
            coords = self._extract_all_coords(geom)
            all_coords.extend(coords)

        if all_coords:
            avg_lon = sum(c[0] for c in all_coords) / len(all_coords)
            avg_lat = sum(c[1] for c in all_coords) / len(all_coords)
            self._center = (avg_lon, avg_lat)
            logger.info(f"[SharedGISContext] 从边界数据更新中心点: {self._center}")

            # 同时更新 bbox
            min_lon = min(c[0] for c in all_coords)
            max_lon = max(c[0] for c in all_coords)
            min_lat = min(c[1] for c in all_coords)
            max_lat = max(c[1] for c in all_coords)
            self._bbox = (min_lon, min_lat, max_lon, max_lat)

    def _extract_all_coords(self, geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
        """从几何对象提取所有坐标"""
        coords = []
        geom_type = geometry.get('type', '')
        geom_coords = geometry.get('coordinates', [])

        if geom_type == 'Point':
            coords.append((geom_coords[0], geom_coords[1]))
        elif geom_type == 'LineString' or geom_type == 'MultiPoint':
            for c in geom_coords:
                coords.append((c[0], c[1]))
        elif geom_type == 'Polygon' or geom_type == 'MultiLineString':
            for ring in geom_coords:
                for c in ring:
                    coords.append((c[0], c[1]))
        elif geom_type == 'MultiPolygon':
            for polygon in geom_coords:
                for ring in polygon:
                    for c in ring:
                        coords.append((c[0], c[1]))

        return coords

    def load_from_data_manager(self) -> None:
        """
        从 GISDataManager 加载用户数据

        将 GISDataManager 中的缓存数据加载到当前上下文。
        """
        try:
            from ..tools.gis.data_manager import GISDataManager
            all_data = GISDataManager.get_all_user_data(self.village_name)
            for data_type, cached in all_data.items():
                self._user_uploaded_data[data_type] = cached.geojson
            logger.info(f"[SharedGISContext] 从 DataManager 加载 {len(all_data)} 个数据类型")
        except ImportError:
            logger.warning("[SharedGISContext] GISDataManager 未安装")

    def get_or_generate_boundary(
        self,
        force_generate: bool = False,
        config: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取或生成边界数据，优先级: 用户上传 > 代理边界生成

        Args:
            force_generate: 强制生成代理边界，忽略用户上传数据
            config: BoundaryFallbackConfig 配置对象

        Returns:
            GeoJSON Polygon 或 None
        """
        # 优先返回用户上传数据
        if not force_generate and self.has_user_data("boundary"):
            boundary_data = self.get_data_by_type("boundary")
            if boundary_data:
                logger.info("[SharedGISContext] 返回用户上传边界数据")
                return boundary_data

        # 生成代理边界
        try:
            from ..tools.core.boundary_fallback import generate_proxy_boundary_with_fallback
            from ..config.boundary_fallback import BoundaryFallbackConfig

            if config is None:
                config = BoundaryFallbackConfig()

            # 收集 GIS 数据用于边界生成
            gis_data = {
                "water": self.get_data_by_type("water"),
                "road": self.get_data_by_type("road"),
                "residential": self.get_data_by_type("residential"),
            }

            result = generate_proxy_boundary_with_fallback(
                center=self.center,
                village_name=self.village_name,
                gis_data=gis_data,
                config=config,
                skip_user_upload=force_generate,
            )

            if result.get("success"):
                strategy_used = result.get("strategy_used", "unknown")
                logger.info(f"[SharedGISContext] 代理边界生成成功，策略: {strategy_used}")
                return result.get("geojson")

            logger.warning(f"[SharedGISContext] 代理边界生成失败: {result.get('error')}")

        except ImportError as e:
            logger.error(f"[SharedGISContext] boundary_fallback 模块未安装: {e}")
        except Exception as e:
            logger.error(f"[SharedGISContext] 边界生成异常: {e}")

        return None

    def get_boundary_generation_info(self) -> Optional[Dict[str, Any]]:
        """获取最近的边界生成结果信息（包括 fallback_history）"""
        return getattr(self, "_boundary_generation_result", None)

    # ============================================
    # 分层数据管理（新增）
    # ============================================

    def ensure_layer_0_ready(self) -> bool:
        """确保基础数据层（Layer 0）已准备好"""
        if self._center is None:
            self._center = self._compute_center()
        return self._center is not None

    def get_layer_0_data(self) -> Dict[str, Any]:
        """获取 Layer 0 基础数据"""
        return {
            "boundary": self.get_data_by_type("boundary"),
            "water": self.get_data_by_type("water"),
            "road": self.get_data_by_type("road"),
            "residential": self.get_data_by_type("residential"),
            "center": self.center,
            "bbox": self.bbox,
        }

    def get_layer_1_data(self) -> Dict[str, Any]:
        """获取 Layer 1 分析数据"""
        return {
            "landuse_current": self.get_data_by_type("landuse_current"),
            "landuse_planned": self.get_data_by_type("landuse_planned"),
            "geological_hazard": self.get_data_by_type("geological_hazard_points"),
            "poi": self.get_data_by_type("poi"),
        }

    def get_layer_2_data(self) -> Dict[str, Any]:
        """
        获取 Layer 2 约束数据（保护红线、建设区）

        自动加载保护约束数据用于规划验证。
        """
        return {
            "farmland_protection": self.get_data_by_type("farmland_protection"),
            "ecological_protection": self.get_data_by_type("ecological_protection"),
            "historical_protection": self.get_data_by_type("historical_protection"),
            "construction_zone": self.get_data_by_type("construction_zone"),
            "hazard_buffer": self.get_data_by_type("hazard_buffer"),
            "three_zones_three_lines": self.get_data_by_type("three_zones_three_lines"),
            "geological_hazard_points": self.get_data_by_type("geological_hazard_points"),
        }

    def get_gd_constraint_data(self, layer_type: str) -> Optional[Dict[str, Any]]:
        """
        获取广东省天地图专题约束数据

        优先级: 用户上传 > GISDataManager缓存 > GD API获取

        Args:
            layer_type: 图层类型 (farmland_protection/ecological_protection/
                        three_zones_three_lines/geological_hazard_points)

        Returns:
            GeoJSON 数据或 None
        """
        # 优先返回用户上传数据
        if self.has_user_data(layer_type):
            logger.debug(f"[SharedGISContext] 返回用户上传数据: {layer_type}")
            return self.get_data_by_type(layer_type)

        # 尝试从 GISDataManager 获取
        try:
            from ..tools.gis.data_manager import GISDataManager
            cached = GISDataManager.get_geojson(self.village_name, layer_type)
            if cached:
                logger.debug(f"[SharedGISContext] 返回缓存数据: {layer_type}")
                return cached
        except ImportError:
            pass

        # 尝试从广东省天地图专题服务获取
        try:
            from ..tools.geocoding.tianditu.gd_service import GDSpecializedService
            gd_service = GDSpecializedService()

            # 使用当前 bbox 获取数据
            bbox = self.bbox
            result = gd_service.fetch_constraint_data(layer_type, bbox)

            if result.success:
                geojson = result.data.get("geojson")
                if geojson and geojson.get("features"):
                    # 缓存到用户数据
                    self._user_uploaded_data[layer_type] = geojson
                    self._data_sources[layer_type] = "gd_tianditu_api"
                    logger.info(f"[SharedGISContext] 从GD API获取数据: {layer_type}, 特征数: {len(geojson.get('features', []))}")
                    return geojson

                # 返回瓦片 URL 信息
                if result.data.get("wms_url"):
                    logger.info(f"[SharedGISContext] GD服务返回瓦片URL: {layer_type}")
                    return {
                        "type": "tile_service",
                        "wms_url": result.data.get("wms_url"),
                        "wmts_url": result.data.get("wmts_url"),
                        "service_id": result.data.get("service_id"),
                        "service_name": result.data.get("service_name"),
                        "metadata": result.metadata,
                    }

            logger.warning(f"[SharedGISContext] GD API获取失败: {result.error}")

        except ImportError as e:
            logger.warning(f"[SharedGISContext] GDSpecializedService 未安装: {e}")
        except Exception as e:
            logger.error(f"[SharedGISContext] GD API获取异常: {e}")

        return None

    def get_protection_zones(self) -> Dict[str, Dict[str, Any]]:
        """获取保护约束区域字典（用于约束验证）"""
        return {
            "farmland": self.get_data_by_type("farmland_protection") or {},
            "ecological": self.get_data_by_type("ecological_protection") or {},
            "historical": self.get_data_by_type("historical_protection") or {},
        }

    def get_constraint_zones_for_layout(self) -> Dict[str, Dict[str, Any]]:
        """获取约束区域（用于空间布局生成）"""
        return {
            "farmland_protection": self.get_data_by_type("farmland_protection"),
            "ecological_protection": self.get_data_by_type("ecological_protection"),
            "historical_protection": self.get_data_by_type("historical_protection"),
            "hazard_zones": self.get_data_by_type("hazard_buffer"),
        }

    def load_jintian_test_data(self) -> None:
        """
        加载金田村测试数据（从 docs/gis/jintian_boundary/）

        用于开发和测试环境。
        """
        try:
            from ..backend.services.jintian_test_data_service import JintianTestDataService
            service = JintianTestDataService()

            # 加载所有数据类型
            all_data = service.load_all_data()

            # 分层存储
            for data_type, geojson in all_data.items():
                if data_type in LAYER_0_TYPES:
                    self._base_data[data_type] = geojson
                elif data_type in LAYER_1_TYPES:
                    self._analysis_data[data_type] = geojson
                elif data_type in LAYER_2_TYPES:
                    self._constraint_data[data_type] = geojson

                # 同时存入用户数据
                self._user_uploaded_data[data_type] = geojson

            logger.info(f"[SharedGISContext] 金田村测试数据已加载: {len(all_data)} 个图层")

        except ImportError:
            logger.warning("[SharedGISContext] JintianTestDataService 未安装")
        except Exception as e:
            logger.error(f"[SharedGISContext] 加载金田村数据失败: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "village_name": self.village_name,
            "center": self.center,
            "center_raw": self.center_raw,
            "bbox": self.bbox,
            "buffer_km": self.buffer_km,
            "user_uploaded_types": self.user_uploaded_types,
            "user_uploaded_data": self.user_uploaded_data,
        }

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> Optional["SharedGISContext"]:
        """从 LangGraph state 创建实例"""
        config = state.get("config", {})
        village_name = config.get("village_name", "")
        if not village_name:
            return None

        instance = cls(village_name=village_name)

        # 加载用户上传数据（从 state 或 GISDataManager）
        user_data = state.get("user_uploaded_data", {})
        if user_data:
            instance._user_uploaded_data = user_data
        else:
            instance.load_from_data_manager()

        return instance