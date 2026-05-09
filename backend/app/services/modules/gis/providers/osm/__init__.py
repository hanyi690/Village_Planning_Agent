"""OpenStreetMap 数据提供者

使用 OSMnx 库获取道路网络数据，补充天地图 WFS 仅提供县级以上道路的限制。
"""

from .provider import OSMProvider
from .types import OSMResult, OSMRoadFeature
from .constants import (
    OVERPASS_ENDPOINT,
    NETWORK_TYPES,
    HIGHWAY_CLASSES,
    VILLAGE_RELEVANT_HIGHWAYS,
)


__all__ = [
    "OSMProvider",
    "OSMResult",
    "OSMRoadFeature",
    "OVERPASS_ENDPOINT",
    "NETWORK_TYPES",
    "HIGHWAY_CLASSES",
    "VILLAGE_RELEVANT_HIGHWAYS",
]