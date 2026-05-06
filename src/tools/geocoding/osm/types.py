"""OSM 数据类型定义"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class OSMRoadFeature:
    """OSM 道路要素"""

    highway_type: str  # OSM highway 类型
    name: Optional[str] = None  # 道路名称
    length: float = 0.0  # 长度（米）
    osm_id: Optional[int] = None  # OSM ID
    geometry: Optional[Dict] = None  # GeoJSON geometry

    def to_geojson_feature(self) -> Dict[str, Any]:
        """转换为 GeoJSON Feature"""
        return {
            "type": "Feature",
            "properties": {
                "highway": self.highway_type,
                "name": self.name or "",
                "length": self.length,
                "osm_id": self.osm_id,
                "source": "osm",
            },
            "geometry": self.geometry,
        }


@dataclass
class OSMResult:
    """OSM 查询结果"""

    success: bool
    data: Optional[Dict[str, Any]] = None  # GeoJSON FeatureCollection
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 统计信息
    total_features: int = 0
    highway_stats: Dict[str, int] = field(default_factory=dict)  # 各类型道路数量

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "total_features": self.total_features,
            "highway_stats": self.highway_stats,
        }