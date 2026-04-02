"""
天地图行政区划边界服务

提供省/市/县/乡/村五级行政区划边界获取功能。
使用天地图 administrative API，国内直接可用。

API 文档：http://lbs.tianditu.gov.cn/home/guide/guide.html
"""

import json
import re
import requests
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from ...utils.logger import get_logger

logger = get_logger(__name__)


# 行政区划级别映射
LEVEL_MAP = {
    "province": "1",     # 省
    "city": "2",         # 市
    "county": "3",       # 县/区
    "town": "4",         # 乡镇/街道
    "village": "5",      # 村/社区
}


@dataclass
class BoundaryResult:
    """
    行政边界获取结果

    Attributes:
        success: 是否成功
        geojson: GeoJSON 边界数据
        admin_code: 行政区划代码
        name: 行政区名称
        level: 行政级别
        center: 中心坐标 (lon, lat)
        error: 错误信息
    """
    success: bool
    geojson: Optional[Dict[str, Any]] = None
    admin_code: Optional[str] = None
    name: Optional[str] = None
    level: Optional[str] = None
    center: Optional[Tuple[float, float]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "success": self.success,
            "geojson": self.geojson,
            "admin_code": self.admin_code,
            "name": self.name,
            "level": self.level,
            "center": self.center,
            "error": self.error,
        }


class TiandituBoundaryService:
    """
    天地图行政区划边界服务

    特点：
    - 坐标系为 WGS-84，无需转换
    - 支持省/市/县/乡/村五级行政区划
    - 国内直接可用，无访问限制
    - 免费额度 1万次/天

    使用方法：
    ```python
    service = TiandituBoundaryService(api_key="your_key")

    # 获取县级边界
    result = service.get_boundary("平远县", level="county")

    # 获取乡镇级边界
    result = service.get_boundary("泗水镇", level="town")

    # 获取村级边界
    result = service.get_boundary("金田村", level="village")
    ```
    """

    API_URL = "http://api.tianditu.gov.cn/administrative"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        初始化天地图行政区划服务

        Args:
            api_key: 天地图 API Key（可从环境变量 TIANDITU_API_KEY 获取）
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key
        self.timeout = timeout

        # 如果未提供 API Key，尝试从配置获取
        if not self.api_key:
            try:
                from ...core.config import TIANDITU_API_KEY
                self.api_key = TIANDITU_API_KEY
            except ImportError:
                logger.warning("[TiandituBoundary] 无法加载配置模块")

        if not self.api_key:
            logger.warning("[TiandituBoundary] API Key 未配置，服务将不可用")

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return bool(self.api_key)

    def get_boundary(
        self,
        name: str,
        level: Optional[str] = None,
        admin_code: Optional[str] = None,
        parent_code: Optional[str] = None
    ) -> BoundaryResult:
        """
        获取行政边界

        Args:
            name: 地名（如"平远县"、"泗水镇"、"金田村"）
            level: 行政级别 (province/city/county/town/village)
            admin_code: 行政区划代码（可选，精确查询）
            parent_code: 上级行政区划代码（可选，缩小查询范围）

        Returns:
            BoundaryResult 包含 GeoJSON 边界数据
        """
        if not self.api_key:
            return BoundaryResult(
                success=False,
                error="天地图 API Key 未配置"
            )

        try:
            # 构建请求参数
            search_type = "query"
            post_data = {}

            if admin_code:
                # 通过行政区划代码查询
                post_data["searchType"] = "byCode"
                post_data["searchWord"] = admin_code
            elif name:
                # 通过地名查询
                post_data["searchType"] = "byName"
                post_data["searchWord"] = name
                if level and level in LEVEL_MAP:
                    post_data["searchLevel"] = LEVEL_MAP[level]
                if parent_code:
                    post_data["parentCode"] = parent_code

            # 发送请求
            params = {
                "postStr": json.dumps(post_data, ensure_ascii=False),
                "type": search_type,
                "tk": self.api_key
            }

            logger.info(f"[TiandituBoundary] 查询边界: {name}, level={level}")
            logger.debug(f"[TiandituBoundary] 请求参数: {params}")

            response = requests.get(
                self.API_URL,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()

            data = response.json()
            logger.debug(f"[TiandituBoundary] 响应数据: {json.dumps(data, ensure_ascii=False)[:500]}")

            return self._parse_response(data, name, level)

        except requests.Timeout:
            logger.warning(f"[TiandituBoundary] 请求超时: {name}")
            return BoundaryResult(success=False, error="请求超时")
        except requests.RequestException as e:
            logger.warning(f"[TiandituBoundary] 请求失败: {e}")
            return BoundaryResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[TiandituBoundary] 解析失败: {e}")
            return BoundaryResult(success=False, error=str(e))

    def get_children(self, parent_code: str) -> BoundaryResult:
        """
        获取下级行政区列表

        Args:
            parent_code: 上级行政区划代码

        Returns:
            BoundaryResult 包含下级行政区列表
        """
        if not self.api_key:
            return BoundaryResult(
                success=False,
                error="天地图 API Key 未配置"
            )

        try:
            post_data = {
                "searchType": "byCode",
                "searchWord": parent_code,
                "childLevel": "all"  # 获取所有下级
            }

            params = {
                "postStr": json.dumps(post_data, ensure_ascii=False),
                "type": "query",
                "tk": self.api_key
            }

            logger.info(f"[TiandituBoundary] 查询下级行政区: {parent_code}")

            response = requests.get(
                self.API_URL,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_children_response(data, parent_code)

        except Exception as e:
            logger.error(f"[TiandituBoundary] 查询下级失败: {e}")
            return BoundaryResult(success=False, error=str(e))

    def _parse_response(
        self,
        data: Dict[str, Any],
        name: str,
        level: Optional[str]
    ) -> BoundaryResult:
        """
        解析天地图 API 响应

        天地图返回格式：
        {
            "status": "0",  # 0 表示成功
            "data": [
                {
                    "name": "平远县",
                    "code": "441426",
                    "level": "3",
                    "lon": "115.891",
                    "lat": "24.567",
                    "bound": "POLYGON(...)" 或坐标数组
                }
            ]
        }
        """
        if data.get("status") != "0":
            return BoundaryResult(
                success=False,
                error=f"API 返回错误: status={data.get('status')}",
            )

        result_list = data.get("data", [])
        if not result_list:
            return BoundaryResult(
                success=False,
                error=f"未找到 {name} 的边界数据",
            )

        # 取第一个匹配结果
        first_result = result_list[0]

        try:
            # 提取基本信息
            admin_code = first_result.get("code", "")
            result_name = first_result.get("name", name)
            result_level = first_result.get("level", "")

            # 提取中心坐标
            lon = float(first_result.get("lon", 0))
            lat = float(first_result.get("lat", 0))
            center = (lon, lat) if lon and lat else None

            # 构建 GeoJSON
            geojson = self._build_geojson(first_result)

            return BoundaryResult(
                success=True,
                geojson=geojson,
                admin_code=admin_code,
                name=result_name,
                level=result_level,
                center=center,
            )

        except (ValueError, TypeError) as e:
            return BoundaryResult(
                success=False,
                error=f"数据解析失败: {e}",
            )

    def _build_geojson(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从天地图数据构建 GeoJSON

        Args:
            data: 天地图返回的单条数据

        Returns:
            GeoJSON Feature 对象
        """
        name = data.get("name", "")
        admin_code = data.get("code", "")
        level = data.get("level", "")
        lon = float(data.get("lon", 0))
        lat = float(data.get("lat", 0))

        # 解析边界数据
        geometry = self._parse_boundary_geometry(data)

        feature = {
            "type": "Feature",
            "properties": {
                "name": name,
                "admin_code": admin_code,
                "level": level,
                "center_lon": lon,
                "center_lat": lat,
                "source": "Tianditu",
            },
            "geometry": geometry,
        }

        return {
            "type": "FeatureCollection",
            "features": [feature],
        }

    def _parse_boundary_geometry(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析边界几何数据

        天地图返回的 bound 字段可能是：
        1. POLYGON 字符串格式：POLYGON((lon lat, lon lat, ...))
        2. 坐标数组格式：[[lon, lat], [lon, lat], ...]
        """
        bound = data.get("bound", "")

        if not bound:
            # 如果没有边界数据，使用中心点作为 Point 几何
            lon = float(data.get("lon", 0))
            lat = float(data.get("lat", 0))
            return {
                "type": "Point",
                "coordinates": [lon, lat],
            }

        # 尝试解析 POLYGON 字符串
        if bound.startswith("POLYGON"):
            return self._parse_polygon_string(bound)

        # 尝试解析坐标数组
        if isinstance(bound, (list, str)):
            try:
                coords = json.loads(bound) if isinstance(bound, str) else bound
                if isinstance(coords, list) and len(coords) >= 3:
                    return {
                        "type": "Polygon",
                        "coordinates": [coords],
                    }
            except (json.JSONDecodeError, TypeError):
                pass

        # 降级到中心点
        lon = float(data.get("lon", 0))
        lat = float(data.get("lat", 0))
        return {
            "type": "Point",
            "coordinates": [lon, lat],
        }

    def _parse_polygon_string(self, polygon_str: str) -> Dict[str, Any]:
        """
        解析 POLYGON 字符串

        格式：POLYGON((lon lat, lon lat, ...))
        或：POLYGON((lon lat, lon lat, ...), (lon lat, ...))  # 多环
        """
        try:
            # 去除 POLYGON 前缀
            content = polygon_str.replace("POLYGON", "").strip()

            # 解析括号内的坐标
            # 格式: ((x y, x y, ...), (x y, ...))
            rings = []

            # 简化解析：提取所有数字对
            # 匹配坐标格式：数字 数字 或 数字,数字
            pairs = re.findall(r'(\d+\.?\d*)[,\s]+(\d+\.?\d*)', content)

            if pairs:
                coords = [[float(p[0]), float(p[1])] for p in pairs]
                # 确保闭合
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                rings.append(coords)

            if rings:
                return {
                    "type": "Polygon",
                    "coordinates": rings,
                }

        except Exception as e:
            logger.warning(f"[TiandituBoundary] POLYGON 解析失败: {e}")

        # 降级处理
        return {
            "type": "Point",
            "coordinates": [0, 0],
        }

    def _parse_children_response(
        self,
        data: Dict[str, Any],
        parent_code: str
    ) -> BoundaryResult:
        """解析下级行政区查询响应"""
        if data.get("status") != "0":
            return BoundaryResult(
                success=False,
                error=f"API 返回错误: status={data.get('status')}",
            )

        children = data.get("data", [])
        if not children:
            return BoundaryResult(
                success=False,
                error=f"未找到 {parent_code} 的下级行政区",
            )

        # 构建包含所有下级的 GeoJSON
        features = []
        for child in children:
            feature = {
                "type": "Feature",
                "properties": {
                    "name": child.get("name", ""),
                    "admin_code": child.get("code", ""),
                    "level": child.get("level", ""),
                },
                "geometry": self._parse_boundary_geometry(child),
            }
            features.append(feature)

        return BoundaryResult(
            success=True,
            geojson={
                "type": "FeatureCollection",
                "features": features,
            },
            name=f"{parent_code} 下级行政区",
        )


# 模块级单例
_boundary_service: Optional[TiandituBoundaryService] = None


def get_boundary_service() -> TiandituBoundaryService:
    """
    获取行政区划边界服务单例

    Returns:
        TiandituBoundaryService 实例
    """
    global _boundary_service
    if _boundary_service is None:
        _boundary_service = TiandituBoundaryService()
    return _boundary_service