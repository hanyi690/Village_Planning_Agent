"""天地图瓦片服务"""
import time
import requests
from typing import Dict, Any, Optional

from .types import TiandituResult
from .constants import (
    TILE_LAYERS,
    ANNOTATION_LAYERS,
    PROJECTIONS,
    TILE_SERVICES,
    TILE_CONFIG,
    BASE_URL
)
from ....core.config import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    GIS_TIMEOUT
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


class TileService:
    """瓦片服务封装"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or TIANDITU_API_KEY
        self.rate_limit = TIANDITU_RATE_LIMIT
        self.timeout = GIS_TIMEOUT
        self._last_request_time = 0

        if not self.api_key:
            logger.warning("[TileService] TIANDITU_API_KEY 未配置")

    def _rate_limit_wait(self):
        """速率限制等待"""
        if self.rate_limit <= 0:
            return
        min_interval = 1.0 / self.rate_limit
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Accept": "image/png",
            "User-Agent": "VillagePlanningAgent/1.0"
        }

    def get_tile_url(
        self,
        layer: str = "vec",
        projection: str = "c",
        x: int = 0,
        y: int = 0,
        z: int = 1,
        server: int = 0
    ) -> str:
        """获取单个瓦片 URL

        Args:
            layer: 图层类型 vec=矢量, img=影像, ter=地形
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影
            x: 瓦片列号
            y: 瓦片行号
            z: 缩放级别 (1-18)
            server: 服务器编号 (0-7)，用于负载均衡

        Returns:
            瓦片图片 URL
        """
        if layer not in TILE_LAYERS:
            logger.warning(f"[TileService] 未知的图层类型: {layer}")
        if projection not in ("c", "w"):
            logger.warning(f"[TileService] 未知的投影类型: {projection}")

        return (
            f"http://t{server}.tianditu.gov.cn/{layer}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={layer}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
            f"&tk={self.api_key}"
        )

    def get_tile_template(
        self,
        layer: str = "vec",
        projection: str = "c"
    ) -> str:
        """获取瓦片模板 URL（用于 Leaflet/Mapbox）

        Args:
            layer: 图层类型 vec=矢量, img=影像, ter=地形
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影

        Returns:
            包含 {s}/{z}/{x}/{y} 占位符的模板 URL
        """
        return (
            f"http://t{{s}}.tianditu.gov.cn/{layer}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={layer}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}"
            f"&tk={self.api_key}"
        )

    def get_annotation_url(
        self,
        annotation_type: str = "cva",
        projection: str = "c",
        x: int = 0,
        y: int = 0,
        z: int = 1,
        server: int = 0
    ) -> str:
        """获取注记图层瓦片 URL

        Args:
            annotation_type: 注记类型 cva=矢量注记, cia=影像注记, cta=地形注记
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影
            x: 瓦片列号
            y: 瓦片行号
            z: 缩放级别
            server: 服务器编号 (0-7)

        Returns:
            注记瓦片 URL
        """
        if annotation_type not in ANNOTATION_LAYERS:
            logger.warning(f"[TileService] 未知的注记类型: {annotation_type}")

        return (
            f"http://t{server}.tianditu.gov.cn/{annotation_type}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={annotation_type}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
            f"&tk={self.api_key}"
        )

    def get_annotation_template(
        self,
        annotation_type: str = "cva",
        projection: str = "c"
    ) -> str:
        """获取注记图层模板 URL"""
        return (
            f"http://t{{s}}.tianditu.gov.cn/{annotation_type}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={annotation_type}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}"
            f"&tk={self.api_key}"
        )

    def get_global_boundary_url(
        self,
        projection: str = "c",
        x: int = 0,
        y: int = 0,
        z: int = 1,
        server: int = 0
    ) -> str:
        """获取全球境界瓦片 URL

        Args:
            projection: 投影类型 c=经纬度, w=墨卡托
            x: 瓦片列号
            y: 瓦片行号
            z: 缩放级别
            server: 服务器编号

        Returns:
            全球境界瓦片 URL
        """
        layer = f"ibo_{projection}"
        return (
            f"http://t{server}.tianditu.gov.cn/ibo_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER=ibo&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
            f"&tk={self.api_key}"
        )

    def get_3d_tiles_url(self, service_type: str = "地名") -> str:
        """获取三维瓦片服务 URL

        Args:
            service_type: 服务类型 地名/地形

        Returns:
            三维瓦片服务 URL
        """
        if service_type == "地名":
            return f"{BASE_URL}/GetTiles?tk={self.api_key}"
        elif service_type == "地形":
            return f"{BASE_URL}/swdx?tk={self.api_key}"
        else:
            logger.warning(f"[TileService] 未知的3D服务类型: {service_type}")
            return ""

    def get_layer_info(self) -> Dict[str, Any]:
        """获取所有可用图层信息"""
        return {
            "base_layers": TILE_LAYERS,
            "annotation_layers": ANNOTATION_LAYERS,
            "projections": PROJECTIONS,
            "tile_services": TILE_SERVICES,
            "zoom_range": TILE_CONFIG["zoom_range"],
            "server_range": TILE_CONFIG["server_range"]
        }


__all__ = ["TileService"]