"""
共享 GIS 数据上下文

统一管理规划流程中的公共 GIS 数据，包括：
- village_name: 村名
- center: 中心点坐标
- bbox: 边界范围

复用 GISDataFetcher 单例进行中心点计算，避免重复创建 TiandituProvider。
"""

from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, field

from ..utils.logger import get_logger

logger = get_logger(__name__)

# 默认中心点（中国中部）
DEFAULT_CENTER = (116.4, 39.9)


@dataclass
class SharedGISContext:
    """共享 GIS 数据上下文 - 统一管理公共 GIS 数据"""

    village_name: str
    buffer_km: float = 5.0

    # 缓存数据
    _center: Optional[Tuple[float, float]] = field(default=None, repr=False)
    _bbox: Optional[Tuple[float, float, float, float]] = field(default=None, repr=False)

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

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "village_name": self.village_name,
            "center": self.center,
            "center_raw": self.center_raw,
            "bbox": self.bbox,
            "buffer_km": self.buffer_km,
        }

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> Optional["SharedGISContext"]:
        """从 LangGraph state 创建实例"""
        config = state.get("config", {})
        village_name = config.get("village_name", "")
        if not village_name:
            return None
        return cls(village_name=village_name)