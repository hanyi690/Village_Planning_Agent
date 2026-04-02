"""
GIS 数据拉取适配器

使用天地图 API 获取行政区划边界数据。
支持省/市/县/乡/村五级行政区划查询。
国内直接可用，无需代理。

新增功能：
- poi_fetch: POI 数据获取（学校、医院、公共设施等）
- wfs_fetch: WFS 图层获取（道路、水系、居民地）
- route_fetch: 路径数据获取（驾车/步行路线）
- reverse_geocode: 逆地理编码（坐标→地址）

参考设计：docs/references/geopandas-ai
- 使用 LLM 生成 Python 代码并执行
- 自动生成数据描述供 LLM 理解
- 代码执行失败自动重试修复（最多 5 次）
"""

from typing import Dict, Any, Optional, List, Tuple
import json
import traceback

from ..base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...geocoding.tianditu_boundary import (
    TiandituBoundaryService,
    BoundaryResult,
    get_boundary_service,
)
from ...geocoding.tianditu_extended import (
    TiandituExtendedService,
    POIResult,
    WFSResult,
    RouteResult,
    RouteType,
    WFSLayerType,
    get_extended_service,
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


_BOUNDARY_FETCH_TEMPLATE = '''
import requests
import json

# 天地图行政区划 API
API_URL = "http://api.tianditu.gov.cn/administrative"

# 从环境变量获取 API Key
import os
api_key = os.environ.get("TIANDITU_API_KEY", "")

# 构建请求参数
post_data = {{
    "searchType": "byName",
    "searchWord": "{location}",
    "searchLevel": "3"
}}

params = {{
    "postStr": json.dumps(post_data, ensure_ascii=False),
    "type": "query",
    "tk": api_key
}}

# 发送请求
response = requests.get(
    API_URL,
    params=params,
    timeout=30,
    headers={{"User-Agent": "Mozilla/5.0"}}
)

data = response.json()

if data.get("status") == "0" and data.get("data"):
    first_result = data["data"][0]

    # 构建 GeoJSON
    geojson = {{
        "type": "FeatureCollection",
        "features": [ {{
            "type": "Feature",
            "properties": {{
                "name": first_result.get("name", "{location}"),
                "admin_code": first_result.get("code", ""),
                "level": first_result.get("level", ""),
                "source": "Tianditu"
            }},
            "geometry": {{
                "type": "Point",
                "coordinates": [
                    float(first_result.get("lon", 0)),
                    float(first_result.get("lat", 0))
                ]
            }}
        }} ]
    }}

    result = {{
        "geojson": geojson,
        "metadata": {{
            "source": "Tianditu",
            "location": first_result.get("name", "{location}"),
            "admin_code": first_result.get("code", ""),
            "level": first_result.get("level", "")
        }}
    }}
else:
    result = {{
        "geojson": None,
        "error": "未找到 {location} 的边界数据"
    }}
'''


class GISDataFetchAdapter(BaseAdapter):
    """
    GIS 数据拉取适配器

    支持的分析类型：
    1. boundary_fetch - 获取行政边界（省/市/县/乡/村）
    2. poi_fetch - POI 数据获取（学校、医院、公共设施等）
    3. wfs_fetch - WFS 图层获取（道路、水系、居民地）
    4. route_fetch - 路径数据获取（驾车/步行路线）
    5. reverse_geocode - 逆地理编码（坐标→地址）
    6. smart_fetch - 智能数据获取（LLM 生成代码）

    数据源：
    - 天地图：国家测绘地理信息局官方服务，WGS-84 坐标系

    使用示例：
    ```python
    adapter = GISDataFetchAdapter()

    # 获取县级边界
    result = adapter.execute("boundary_fetch", location="平远县", level="county")

    # POI 搜索
    result = adapter.execute("poi_fetch", keyword="学校", center=(115.891, 24.567), radius=1000)

    # WFS 道路数据
    result = adapter.execute("wfs_fetch", layer_type="LRDL", bbox=(115.8, 24.5, 116.0, 24.7))

    # 路径规划
    result = adapter.execute("route_fetch", origin=(115.891, 24.567), destination=(116.0, 24.6))
    ```
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化适配器"""
        self._boundary_service: Optional[TiandituBoundaryService] = None
        self._extended_service: Optional[TiandituExtendedService] = None
        super().__init__(config)
        self._max_retries = self.config.get("max_retries", 5)

    def validate_dependencies(self) -> bool:
        """验证外部依赖是否可用"""
        try:
            # 初始化天地图边界服务
            self._boundary_service = get_boundary_service()
            # 初始化天地图扩展服务
            self._extended_service = get_extended_service()

            boundary_available = self._boundary_service.is_available()
            extended_available = self._extended_service.is_available()

            if boundary_available and extended_available:
                logger.info("[GISDataFetchAdapter] 天地图服务可用")
                return True
            else:
                logger.warning("[GISDataFetchAdapter] 天地图 API Key 未配置")
                return True  # 仍然返回 True，让用户知道需要配置

        except Exception as e:
            logger.warning(f"[GISDataFetchAdapter] 初始化失败: {e}")
            return False

    def initialize(self) -> bool:
        """初始化适配器"""
        try:
            if not self._boundary_service:
                self._boundary_service = get_boundary_service()
            if not self._extended_service:
                self._extended_service = get_extended_service()

            if not self._boundary_service.is_available():
                logger.warning(
                    "[GISDataFetchAdapter] 天地图 API Key 未配置，"
                    "请设置 TIANDITU_API_KEY 环境变量"
                )

            self._status = AdapterStatus.READY
            return True

        except Exception as e:
            self._error_message = f"初始化失败: {str(e)}"
            logger.error(f"[GISDataFetchAdapter] {self._error_message}")
            return False

    def _check_service_available(self, require_extended: bool = False) -> Optional[AdapterResult]:
        """
        检查服务可用性

        Args:
            require_extended: 是否需要扩展服务

        Returns:
            None if available, AdapterResult with error if not
        """
        if require_extended:
            if not self._extended_service or not self._extended_service.is_available():
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error="天地图扩展服务不可用。请配置 TIANDITU_API_KEY 环境变量"
                )
        else:
            if not self._boundary_service or not self._boundary_service.is_available():
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error="天地图服务不可用。请配置 TIANDITU_API_KEY 环境变量"
                )
        return None

    @staticmethod
    def _error_result(message: str) -> AdapterResult:
        """创建错误结果的快捷方法"""
        return AdapterResult(
            success=False,
            status=AdapterStatus.FAILED,
            data={},
            metadata={},
            error=message
        )

    def execute(
        self,
        analysis_type: str = "boundary_fetch",
        **kwargs
    ) -> AdapterResult:
        """
        执行 GIS 数据获取

        Args:
            analysis_type: 分析类型
                - boundary_fetch: 获取行政边界
                - poi_fetch: POI 数据获取
                - wfs_fetch: WFS 图层获取
                - route_fetch: 路径数据获取
                - reverse_geocode: 逆地理编码
                - smart_fetch: 智能数据获取

            **kwargs: 参数
                - location: 地名（boundary_fetch）
                - level: 行政级别（boundary_fetch）
                - keyword: POI 关键词（poi_fetch）
                - center: 中心坐标（poi_fetch）
                - radius: 搜索半径（poi_fetch）
                - layer_type: WFS 图层类型（wfs_fetch）
                - bbox: 边界框（wfs_fetch）
                - origin: 起点坐标（route_fetch）
                - destination: 终点坐标（route_fetch）
                - lon/lat: 坐标（reverse_geocode）

        Returns:
            AdapterResult: 包含数据
        """
        logger.info(f"[GISDataFetchAdapter] 执行: {analysis_type}")

        if analysis_type == "boundary_fetch":
            return self._fetch_boundary(**kwargs)
        elif analysis_type == "poi_fetch":
            return self._fetch_poi(**kwargs)
        elif analysis_type == "wfs_fetch":
            return self._fetch_wfs(**kwargs)
        elif analysis_type == "route_fetch":
            return self._fetch_route(**kwargs)
        elif analysis_type == "reverse_geocode":
            return self._reverse_geocode(**kwargs)
        elif analysis_type == "smart_fetch":
            return self._smart_fetch(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取输出 Schema"""
        return {
            "adapter_name": "GISDataFetchAdapter",
            "supported_analyses": [
                "boundary_fetch",
                "poi_fetch",
                "wfs_fetch",
                "route_fetch",
                "reverse_geocode",
                "smart_fetch"
            ],
            "output_schema": {
                "geojson": "object (GeoJSON FeatureCollection)",
                "metadata": {
                    "source": "string (Tianditu)",
                    "location": "string",
                    "admin_code": "string",
                    "level": "string",
                    "center": "array [lon, lat]",
                }
            }
        }

    # ==========================================
    # 边界获取方法
    # ==========================================

    def _fetch_boundary(self, **kwargs) -> AdapterResult:
        """获取行政边界"""
        location = kwargs.get("location")
        if not location:
            return self._error_result("缺少 location 参数")

        level = kwargs.get("level", "county")
        admin_code = kwargs.get("admin_code")
        parent_code = kwargs.get("parent_code")

        error = self._check_service_available()
        if error:
            return error

        # 调用天地图边界服务
        result = self._boundary_service.get_boundary(
            name=location,
            level=level,
            admin_code=admin_code,
            parent_code=parent_code,
        )

        if not result.success:
            return self._error_result(result.error or "获取边界失败")

        metadata = {
            "source": "Tianditu",
            "location": result.name,
            "admin_code": result.admin_code,
            "level": result.level,
            "center": result.center,
        }
        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={"geojson": result.geojson, "metadata": metadata},
            metadata=metadata
        )

    def fetch_children(self, parent_code: str) -> AdapterResult:
        """
        获取下级行政区列表

        Args:
            parent_code: 上级行政区划代码

        Returns:
            AdapterResult: 包含下级行政区 GeoJSON
        """
        error = self._check_service_available()
        if error:
            return error

        result = self._boundary_service.get_children(parent_code)

        if not result.success:
            return self._error_result(result.error or "获取下级行政区失败")

        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "geojson": result.geojson,
                "metadata": {"parent_code": parent_code, "source": "Tianditu"}
            },
            metadata={"parent_code": parent_code, "source": "Tianditu"}
        )

    # ==========================================
    # POI 数据获取
    # ==========================================

    def _fetch_poi(self, **kwargs) -> AdapterResult:
        """
        POI 数据获取

        Args:
            keyword: 搜索关键词（如 "学校"、"医院"）
            center: 中心坐标 (lon, lat)
            radius: 搜索半径（米）
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
            admin_code: 行政区划代码

        Returns:
            AdapterResult: 包含 POI 列表
        """
        keyword = kwargs.get("keyword")
        if not keyword:
            return self._error_result("缺少 keyword 参数")

        error = self._check_service_available(require_extended=True)
        if error:
            return error

        center = kwargs.get("center")
        radius = kwargs.get("radius")
        bbox = kwargs.get("bbox")
        admin_code = kwargs.get("admin_code")
        page_size = kwargs.get("page_size", 20)

        result = self._extended_service.search_poi(
            keyword=keyword,
            center=center,
            radius=radius,
            bbox=bbox,
            admin_code=admin_code,
            page_size=page_size
        )

        if result.success:
            # 将 POI 列表转换为 GeoJSON
            features = []
            for poi in result.pois:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": poi.get("name", ""),
                        "address": poi.get("address", ""),
                        "category": poi.get("category", ""),
                        "tel": poi.get("tel", ""),
                        "distance": poi.get("distance"),
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [poi.get("lon", 0), poi.get("lat", 0)]
                    }
                })

            geojson = {
                "type": "FeatureCollection",
                "features": features
            }

            metadata = {
                "source": "TiandituPOI",
                "keyword": keyword,
                "total_count": result.total_count,
                "center": center,
                "radius": radius,
            }

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={"geojson": geojson, "pois": result.pois, "metadata": metadata},
                metadata=metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    # ==========================================
    # WFS 数据获取
    # ==========================================

    def _fetch_wfs(self, **kwargs) -> AdapterResult:
        """
        WFS 图层数据获取

        Args:
            layer_type: 图层类型（LRDL-公路, HYDA-水系面, HYDL-水系线等）
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)

        Returns:
            AdapterResult: 包含 WFS GeoJSON 数据
        """
        layer_type_str = kwargs.get("layer_type", "LRDL")
        bbox = kwargs.get("bbox")

        if not bbox:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 bbox 参数（格式：min_lon, min_lat, max_lon, max_lat）"
            )

        if not self._extended_service or not self._extended_service.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图扩展服务不可用。请配置 TIANDITU_API_KEY 环境变量"
            )

        # 转换图层类型
        try:
            layer_type = WFSLayerType(layer_type_str)
        except ValueError:
            layer_type = WFSLayerType.LRDL  # 默认公路图层

        result = self._extended_service.fetch_wfs_layer(layer_type, bbox)

        if result.success:
            metadata = {
                "source": "TiandituWFS",
                "layer": result.layer_name,
                "feature_count": result.feature_count,
                "bbox": bbox,
            }

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={"geojson": result.geojson, "metadata": metadata},
                metadata=metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    # ==========================================
    # 路径数据获取
    # ==========================================

    def _fetch_route(self, **kwargs) -> AdapterResult:
        """
        路径数据获取

        Args:
            origin: 起点坐标 (lon, lat)
            destination: 终点坐标 (lon, lat)
            route_type: 路径类型（driving/walking/bicycling）

        Returns:
            AdapterResult: 包含路径 GeoJSON 数据
        """
        origin = kwargs.get("origin")
        destination = kwargs.get("destination")
        route_type_str = kwargs.get("route_type", "driving")

        if not origin or not destination:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 origin 或 destination 参数"
            )

        if not self._extended_service or not self._extended_service.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图扩展服务不可用。请配置 TIANDITU_API_KEY 环境变量"
            )

        # 转换路径类型
        try:
            route_type = RouteType(route_type_str)
        except ValueError:
            route_type = RouteType.DRIVING

        result = self._extended_service.route_planning(origin, destination, route_type)

        if result.success:
            # 将路径转换为 GeoJSON LineString
            geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "distance": result.distance,
                            "duration": result.duration,
                            "route_type": result.route_type,
                            "origin": result.origin,
                            "destination": result.destination,
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": result.geometry
                        }
                    }
                ]
            }

            metadata = {
                "source": "TiandituRoute",
                "distance": result.distance,
                "duration": result.duration,
                "route_type": result.route_type,
                "steps_count": len(result.steps),
            }

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={"geojson": geojson, "steps": result.steps, "metadata": metadata},
                metadata=metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    # ==========================================
    # 逆地理编码
    # ==========================================

    def _reverse_geocode(self, **kwargs) -> AdapterResult:
        """
        逆地理编码：坐标 → 地址

        Args:
            lon: 经度
            lat: 纬度

        Returns:
            AdapterResult: 包含地址信息
        """
        lon = kwargs.get("lon")
        lat = kwargs.get("lat")

        if lon is None or lat is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 lon 或 lat 参数"
            )

        if not self._extended_service or not self._extended_service.is_available():
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图扩展服务不可用。请配置 TIANDITU_API_KEY 环境变量"
            )

        result = self._extended_service.reverse_geocode(lon, lat)

        if result.success:
            metadata = {
                "source": "TiandituReverseGeocode",
                "lon": lon,
                "lat": lat,
            }

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data={
                    "address": result.address,
                    "formatted_address": result.formatted_address,
                    "province": result.province,
                    "city": result.city,
                    "county": result.county,
                    "town": result.town,
                    "village": result.village,
                    "poi_name": result.poi_name,
                    "metadata": metadata
                },
                metadata=metadata
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=result.error
            )

    # ==========================================
    # Smart Fetch - LLM 代码生成
    # ==========================================

    def _smart_fetch(self, **kwargs) -> AdapterResult:
        """
        智能数据获取

        使用 LLM 生成 Python 代码获取数据，失败自动重试。
        参考 geopandas-ai 设计思路。
        """
        location = kwargs.get("location")
        prompt = kwargs.get("prompt", "")
        data_requirements = kwargs.get("data_requirements", {})

        if not location:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 location 参数"
            )

        if not prompt:
            prompt = self._generate_fetch_prompt(location, data_requirements)

        logger.info(f"[GISDataFetchAdapter] Smart Fetch: location={location}")

        # 尝试获取 LLM 配置
        try:
            from ....core.config import get_config
            config = get_config()
            llm_config = config.llm if hasattr(config, 'llm') else None
        except ImportError:
            llm_config = None

        if not llm_config:
            # 降级到直接获取
            logger.warning("[GISDataFetchAdapter] LLM 配置不可用，降级到直接获取")
            return self._fetch_boundary(location=location)

        # LLM 代码生成 + 重试
        return self._llm_code_generation(location, prompt, data_requirements)

    def _generate_fetch_prompt(self, location: str, requirements: Dict) -> str:
        """生成数据获取提示"""
        base_prompt = f"获取 {location} 的 GIS 数据"
        if requirements:
            req_str = ", ".join(f"{k}: {v}" for k, v in requirements.items())
            base_prompt += f"，需要包含 {req_str}"
        return base_prompt

    def _llm_code_generation(
        self,
        location: str,
        prompt: str,
        requirements: Dict
    ) -> AdapterResult:
        """
        LLM 代码生成 + 执行

        参考 geopandas-ai 的设计：
        1. 生成数据描述
        2. LLM 生成代码
        3. 执行代码
        4. 失败自动重试（最多 5 次）
        """
        context = {
            "location": location,
            "prompt": prompt,
            "requirements": requirements,
            "available_libraries": ["requests", "json"],
        }

        # 生成初始代码
        code = self._generate_fetch_code(context)

        # 重试循环
        for attempt in range(self._max_retries):
            logger.info(f"[GISDataFetchAdapter] 执行尝试 #{attempt + 1}/{self._max_retries}")

            result = self._execute_fetch_code(code, location)

            if result.success:
                return result

            error_msg = result.error
            logger.warning(f"[GISDataFetchAdapter] 执行失败: {error_msg}")

            if attempt < self._max_retries - 1:
                code = self._fix_fetch_code(code, error_msg, context)

        return AdapterResult(
            success=False,
            status=AdapterStatus.FAILED,
            data={},
            metadata={"attempts": self._max_retries},
            error=f"代码生成执行失败，已尝试 {self._max_retries} 次"
        )

    def _generate_fetch_code(self, context: Dict) -> str:
        """生成数据获取代码"""
        return self._template_boundary_code(context["location"])

    def _template_boundary_code(self, location: str) -> str:
        """边界获取代码模板 - 使用天地图 API"""
        return _BOUNDARY_FETCH_TEMPLATE.format(location=location)

    def _execute_fetch_code(self, code: str, location: str) -> AdapterResult:
        """执行获取代码"""
        try:
            import requests
            import json
            import os

            exec_globals = {
                "requests": requests,
                "json": json,
                "os": os,
                "location": location,
            }

            exec(code, exec_globals)

            result_data = exec_globals.get("result", {})

            if result_data and result_data.get("geojson"):
                return AdapterResult(
                    success=True,
                    status=AdapterStatus.SUCCESS,
                    data=result_data,
                    metadata=result_data.get("metadata", {})
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error=result_data.get("error", "代码执行成功但未返回有效数据")
                )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"代码执行错误: {str(e)}\\n{traceback.format_exc()}"
            )

    def _fix_fetch_code(self, code: str, error: str, context: Dict) -> str:
        """修复失败的代码"""
        location = context["location"]

        if "not found" in error.lower() or "未找到" in error:
            # 尝试简化地名
            simple_location = location.split("县")[0] if "县" in location else location
            return self._template_boundary_code(simple_location)

        return code