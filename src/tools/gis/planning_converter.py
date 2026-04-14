"""
规划文字转换模块

将 LLM 生成的文字规划转换为 GIS 几何数据。
支持方位描述、面积描述、相对位置、设施点位等转换。

复用项目已有的 Agent/DS 模型处理自然语言解析。
"""

import json
import math
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple, Union
from enum import Enum

logger = logging.getLogger(__name__)


# ==========================================
# 常量定义
# ==========================================

# 几何生成常量
DEFAULT_AREA_M2 = 50000  # 默认面积 5 公顷
DEFAULT_RADIUS_M = 500   # 默认半径 500 米
CIRCLE_SEGMENTS = 32     # 圆形多边形边数
SECTOR_ARC_POINTS = 16   # 扇形弧线点数
METERS_PER_DEGREE = 111000  # 每度对应的米数

# 位置偏移常量（度）
OFFSET_DEGREES_500M = 0.005    # 约 500 米
OFFSET_DEGREES_DIRECTIONAL = 0.003  # 方向偏移
OFFSET_DEGREES_SMALL = 0.002   # 小偏移
OFFSET_DEGREES_MIN = 0.001     # 最小偏移

# 规划类型常量
ZONE_TYPES = ['种植区', '养殖区', '加工区', '居住区', '生态区', '旅游区', '商业区', '工业区']
FACILITY_TYPES = ['加工中心', '蔬菜加工', '养殖基地', '仓储物流', '旅游景点', '服务中心', '学校', '医院', '超市']
LOCATION_KEYWORDS = ['村口', '中心', '东侧', '西侧', '南侧', '北侧', '河边', '路口']
AXIS_TYPES = ['发展主轴', '发展次轴', '发展带', '连接轴']

# 预编译正则表达式
_RE_AREA = re.compile(r'面积约?(\d+)(亩|公顷|平方米|m2|km2)')
_RE_NAME = re.compile(r'["""](.+?)["""]|(.+?)种植区|(.+?)养殖区')
_RE_NEW_FACILITY = re.compile(r'新建(.+?)中心|新建(.+?)基地|新建(.+?)设施')
_RE_RELATIVE = re.compile(r'距(.+?)(\d+)米|在(.+?)附近')
_RE_AXIS_NAME = re.compile(r'["""](.+?)["""]|沿(.+?)发展带')
_RE_ENDPOINTS = re.compile(r'连接(.+?)和(.+?)|连接东西|连接南北')


class Direction(Enum):
    """方位枚举"""
    NORTH = "north"
    NORTH_EAST = "north_east"
    EAST = "east"
    SOUTH_EAST = "south_east"
    SOUTH = "south"
    SOUTH_WEST = "south_west"
    WEST = "west"
    NORTH_WEST = "north_west"
    CENTER = "center"


# 方位角度映射
DIRECTION_ANGLES = {
    Direction.NORTH: (0, 45),
    Direction.NORTH_EAST: (45, 90),
    Direction.EAST: (90, 135),
    Direction.SOUTH_EAST: (135, 180),
    Direction.SOUTH: (180, 225),
    Direction.SOUTH_WEST: (225, 270),
    Direction.WEST: (270, 315),
    Direction.NORTH_WEST: (315, 360),
}

# 方位关键词映射
DIRECTION_KEYWORDS = {
    '东': Direction.EAST,
    '东部': Direction.EAST,
    '东边': Direction.EAST,
    '南': Direction.SOUTH,
    '南部': Direction.SOUTH,
    '南边': Direction.SOUTH,
    '西': Direction.WEST,
    '西部': Direction.WEST,
    '西边': Direction.WEST,
    '北': Direction.NORTH,
    '北部': Direction.NORTH,
    '北边': Direction.NORTH,
    '东北': Direction.NORTH_EAST,
    '东南': Direction.SOUTH_EAST,
    '西南': Direction.SOUTH_WEST,
    '西北': Direction.NORTH_WEST,
    '中心': Direction.CENTER,
    '中部': Direction.CENTER,
    '核心': Direction.CENTER,
}

# 面积单位转换（平方米）
AREA_UNITS = {
    '亩': 666.67,
    '公顷': 10000,
    'km2': 1000000,
    '平方米': 1,
    'm2': 1,
}


@dataclass
class ZoneParsedResult:
    """解析后的区域描述"""
    direction: Optional[Direction] = None
    angle_range: Tuple[float, float] = (0, 360)
    area_m2: Optional[float] = None
    radius_m: Optional[float] = None
    zone_type: Optional[str] = None
    name: Optional[str] = None
    constraints: List[str] = field(default_factory=list)


@dataclass
class FacilityParsedResult:
    """解析后的设施描述"""
    name: Optional[str] = None
    facility_type: Optional[str] = None
    location_description: Optional[str] = None
    coordinates: Optional[Tuple[float, float]] = None
    relative_to: Optional[str] = None
    buffer_km: Optional[float] = None


class PlanningTextConverter:
    """规划文字转换器"""

    def __init__(self):
        """初始化转换器"""
        self._agent = None

    def _get_agent(self):
        """获取 Agent 实例（延迟加载）"""
        if self._agent is None:
            try:
                # 尝试导入项目的 Agent
                from ...agents import get_fast_agent
                self._agent = get_fast_agent()
                logger.debug("[规划转换] Agent 加载成功")
            except ImportError:
                logger.warning("[规划转换] Agent 未可用，使用规则解析")
                self._agent = None
        return self._agent

    def convert_zone_description(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        方位+面积描述 → 功能区多边形

        Args:
            description: 区域描述，如 "东部种植区，面积约200亩"
            context: 上下文，包含 center, boundary, water 等参考数据

        Returns:
            GeoJSON Feature 或 FeatureCollection
        """
        # 解析描述
        parsed = self._parse_zone_description(description)

        if parsed.area_m2 is None:
            logger.warning("[规划转换] 无法解析面积，使用默认值")
            parsed.area_m2 = DEFAULT_AREA_M2

        # 获取中心点
        center = context.get('center')
        if center is None:
            # 尝试从 GIS 缓存获取
            gis_cache = context.get('gis_analysis_results', {})
            auto_fetched = gis_cache.get('_auto_fetched')
            if auto_fetched and hasattr(auto_fetched, 'center'):
                center = auto_fetched.center

        if center is None:
            logger.error("[规划转换] 缺少中心点，无法生成几何")
            return {'type': 'FeatureCollection', 'features': []}

        # 生成几何
        geometry = self._generate_zone_geometry(parsed, center, context)

        # 构建 Feature
        feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'name': parsed.name or description[:20],
                'zone_type': parsed.zone_type or '规划区',
                'area_m2': parsed.area_m2,
                'direction': parsed.direction.value if parsed.direction else 'unknown',
                'source': 'planning_text_conversion',
            }
        }

        return {
            'type': 'FeatureCollection',
            'features': [feature]
        }

    def convert_facility_description(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        设施描述 → 设施点位

        Args:
            description: 设施描述，如 "在村口新建蔬菜加工中心"
            context: 上下文

        Returns:
            GeoJSON Feature 或 FeatureCollection
        """
        parsed = self._parse_facility_description(description)

        # 尝试获取坐标
        if parsed.coordinates is None:
            parsed.coordinates = self._estimate_facility_location(parsed, context)

        if parsed.coordinates is None:
            logger.warning("[规划转换] 无法确定设施位置")
            return {'type': 'FeatureCollection', 'features': []}

        # 构建 Feature
        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': list(parsed.coordinates),
            },
            'properties': {
                'name': parsed.name or description[:20],
                'facility_type': parsed.facility_type or '设施',
                'description': description,
                'source': 'planning_text_conversion',
            }
        }

        # 如果有缓冲区，添加缓冲圆
        features = [feature]
        if parsed.buffer_km:
            buffer_feature = self._create_buffer_circle(parsed.coordinates, parsed.buffer_km)
            buffer_feature['properties']['name'] = f"{parsed.name}辐射范围"
            features.append(buffer_feature)

        return {
            'type': 'FeatureCollection',
            'features': features
        }

    def convert_axis_description(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        发展轴描述 → 线条几何

        Args:
            description: 轴线描述，如 "沿河发展带，连接东西两个组团"
            context: 上下文

        Returns:
            GeoJSON Feature
        """
        # 解析轴线描述
        parsed = self._parse_axis_description(description)

        # 获取参考线（如河流）
        reference_line = None
        water_geojson = context.get('water')
        if water_geojson and 'features' in water_geojson:
            # 找到主要河流
            for feat in water_geojson['features']:
                geom = feat.get('geometry', {})
                if geom.get('type') == 'LineString':
                    reference_line = geom.get('coordinates')
                    break

        # 生成轴线几何
        if reference_line:
            # 基于参考线生成
            geometry = self._generate_axis_from_reference(reference_line, parsed)
        else:
            # 基于描述生成（需要两个端点）
            geometry = self._generate_axis_from_endpoints(parsed, context)

        if geometry is None:
            logger.warning("[规划转换] 无法生成发展轴几何")
            return {'type': 'FeatureCollection', 'features': []}

        feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'name': parsed.get('name', description[:20]),
                'axis_type': parsed.get('axis_type', '发展轴'),
                'source': 'planning_text_conversion',
            }
        }

        return {
            'type': 'FeatureCollection',
            'features': [feature]
        }

    def _parse_zone_description(self, description: str) -> ZoneParsedResult:
        """解析区域描述"""
        result = ZoneParsedResult()

        # 解析方位
        for keyword, direction in DIRECTION_KEYWORDS.items():
            if keyword in description:
                result.direction = direction
                result.angle_range = DIRECTION_ANGLES.get(direction, (0, 360))
                break

        # 解析面积
        match = _RE_AREA.search(description)
        if match:
            value = float(match.group(1))
            unit = match.group(2)
            result.area_m2 = value * AREA_UNITS.get(unit, 1)
            # 计算半径
            result.radius_m = math.sqrt(result.area_m2 / math.pi)

        # 解析区域类型
        for zt in ZONE_TYPES:
            if zt in description:
                result.zone_type = zt
                break

        # 解析名称（引号内或关键词前）
        name_match = _RE_NAME.search(description)
        if name_match:
            result.name = name_match.group(1) or name_match.group(2) or name_match.group(3)

        return result

    def _parse_facility_description(self, description: str) -> FacilityParsedResult:
        """解析设施描述"""
        result = FacilityParsedResult()

        # 解析设施类型
        for ft in FACILITY_TYPES:
            if ft in description:
                result.facility_type = ft
                break

        # 解析名称
        new_match = _RE_NEW_FACILITY.search(description)
        if new_match:
            result.name = f"新建{new_match.group(1) or new_match.group(2)}中心"

        # 解析位置描述
        for lk in LOCATION_KEYWORDS:
            if lk in description:
                result.location_description = lk
                break

        # 解析相对位置
        relative_match = _RE_RELATIVE.search(description)
        if relative_match:
            result.relative_to = relative_match.group(1) or relative_match.group(3)

        return result

    def _parse_axis_description(self, description: str) -> Dict[str, Any]:
        """解析轴线描述"""
        result = {'name': '', 'axis_type': '发展轴', 'endpoints': []}

        # 解析轴线类型
        for at in AXIS_TYPES:
            if at in description:
                result['axis_type'] = at
                break

        # 解析名称
        name_match = _RE_AXIS_NAME.search(description)
        if name_match:
            result['name'] = name_match.group(1) or f"{name_match.group(2)}发展带"

        # 解析端点
        endpoints_match = _RE_ENDPOINTS.search(description)
        if endpoints_match:
            if '东西' in description:
                result['endpoints'] = ['east', 'west']
            elif '南北' in description:
                result['endpoints'] = ['north', 'south']
            else:
                result['endpoints'] = [endpoints_match.group(1), endpoints_match.group(2)]

        return result

    def _generate_zone_geometry(
        self,
        parsed: ZoneParsedResult,
        center: Tuple[float, float],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成区域几何"""
        lon, lat = center

        # 根据解析结果生成几何
        if parsed.direction == Direction.CENTER:
            # 中心区域 - 生成圆形
            return self._create_circle_geometry(lon, lat, parsed.radius_m or DEFAULT_RADIUS_M)
        else:
            # 方位区域 - 生成扇形
            angle_min, angle_max = parsed.angle_range
            radius = parsed.radius_m or DEFAULT_RADIUS_M

            return self._create_sector_geometry(lon, lat, radius, angle_min, angle_max)

    def _create_circle_geometry(
        self,
        lon: float,
        lat: float,
        radius_m: float
    ) -> Dict[str, Any]:
        """创建圆形几何"""
        # 将米转换为经纬度偏移（近似）
        lat_correction = math.cos(math.radians(lat))
        meter_to_deg_lon = 1 / METERS_PER_DEGREE / lat_correction
        meter_to_deg_lat = 1 / METERS_PER_DEGREE

        coordinates = []
        for i in range(CIRCLE_SEGMENTS):
            angle = 2 * math.pi * i / CIRCLE_SEGMENTS
            dx = radius_m * math.cos(angle) * meter_to_deg_lon
            dy = radius_m * math.sin(angle) * meter_to_deg_lat
            coordinates.append([lon + dx, lat + dy])

        # 闭合环
        coordinates.append(coordinates[0])

        return {
            'type': 'Polygon',
            'coordinates': [coordinates]
        }

    def _create_sector_geometry(
        self,
        lon: float,
        lat: float,
        radius_m: float,
        angle_min: float,
        angle_max: float
    ) -> Dict[str, Any]:
        """创建扇形几何"""
        # 将角度转换为弧度（地理角度：北=0°，东=90°）
        # 数学角度：东=0°，北=90°
        # 转换：地理角度 + 90° = 数学角度（mod 360）

        def geo_to_math_angle(geo_angle):
            return (geo_angle + 90) % 360

        math_min = math.radians(geo_to_math_angle(angle_min))
        math_max = math.radians(geo_to_math_angle(angle_max))

        # 米转经纬度
        lat_correction = math.cos(math.radians(lat))
        meter_to_deg_lon = 1 / METERS_PER_DEGREE / lat_correction
        meter_to_deg_lat = 1 / METERS_PER_DEGREE

        # 生成扇形边界点
        coordinates = []

        # 中心点
        coordinates.append([lon, lat])

        # 弧线点
        for i in range(SECTOR_ARC_POINTS + 1):
            angle = math_min + (math_max - math_min) * i / SECTOR_ARC_POINTS
            dx = radius_m * math.cos(angle) * meter_to_deg_lon
            dy = radius_m * math.sin(angle) * meter_to_deg_lat
            coordinates.append([lon + dx, lat + dy])

        # 回到中心点
        coordinates.append([lon, lat])

        return {
            'type': 'Polygon',
            'coordinates': [coordinates]
        }

    def _create_buffer_circle(
        self,
        center: Tuple[float, float],
        buffer_km: float
    ) -> Dict[str, Any]:
        """创建缓冲圆 Feature"""
        lon, lat = center
        radius_m = buffer_km * 1000

        geometry = self._create_circle_geometry(lon, lat, radius_m)

        return {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'type': 'buffer',
                'radius_km': buffer_km,
            }
        }

    def _estimate_facility_location(
        self,
        parsed: FacilityParsedResult,
        context: Dict[str, Any]
    ) -> Optional[Tuple[float, float]]:
        """估算设施位置"""
        center = context.get('center')
        if center is None:
            return None

        lon, lat = center

        # 根据位置描述估算偏移
        if parsed.location_description == '村口':
            return (lon - OFFSET_DEGREES_500M, lat)
        elif parsed.location_description == '中心':
            return center
        elif parsed.location_description == '东侧':
            return (lon + OFFSET_DEGREES_DIRECTIONAL, lat)
        elif parsed.location_description == '西侧':
            return (lon - OFFSET_DEGREES_DIRECTIONAL, lat)
        elif parsed.location_description == '南侧':
            return (lon, lat - OFFSET_DEGREES_DIRECTIONAL)
        elif parsed.location_description == '北侧':
            return (lon, lat + OFFSET_DEGREES_DIRECTIONAL)
        elif parsed.location_description == '河边':
            # 尝试从水系数据获取
            water_geojson = context.get('water')
            if water_geojson and 'features' in water_geojson:
                for feat in water_geojson['features']:
                    geom = feat.get('geometry', {})
                    if geom.get('type') == 'LineString':
                        coords = geom.get('coordinates', [])
                        if coords:
                            # 取河流中点偏移
                            mid_idx = len(coords) // 2
                            river_point = coords[mid_idx]
                            return (river_point[0] + OFFSET_DEGREES_MIN, river_point[1])

        # 默认：中心偏移
        return (lon + OFFSET_DEGREES_SMALL, lat + OFFSET_DEGREES_SMALL)

    def _generate_axis_from_reference(
        self,
        reference_line: List[List[float]],
        parsed: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """基于参考线生成轴线"""
        if not reference_line:
            return None

        # 简化：取参考线的主要段
        # 取起点和终点
        start = reference_line[0]
        end = reference_line[-1]

        return {
            'type': 'LineString',
            'coordinates': [start, end]
        }

    def _generate_axis_from_endpoints(
        self,
        parsed: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """基于端点生成轴线"""
        center = context.get('center')
        if center is None:
            return None

        lon, lat = center

        endpoints = parsed.get('endpoints', [])
        if not endpoints:
            return None

        # 根据端点方向生成坐标
        offset = 0.005  # 约500米
        coords = []

        for ep in endpoints:
            if ep == 'east':
                coords.append([lon + offset, lat])
            elif ep == 'west':
                coords.append([lon - offset, lat])
            elif ep == 'north':
                coords.append([lon, lat + offset])
            elif ep == 'south':
                coords.append([lon, lat - offset])
            else:
                # 未知端点，跳过
                pass

        if len(coords) < 2:
            return None

        return {
            'type': 'LineString',
            'coordinates': coords
        }


def convert_planning_text_to_geojson(
    text: str,
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    便捷函数：将规划文字转换为 GeoJSON

    Args:
        text: 规划文字描述
        context: 上下文数据

    Returns:
        GeoJSON FeatureCollection
    """
    converter = PlanningTextConverter()

    # 判断描述类型
    if any(kw in text for kw in ['种植区', '养殖区', '加工区', '居住区', '功能区', '区域', '面积约']):
        return converter.convert_zone_description(text, context)
    elif any(kw in text for kw in ['新建', '设施', '中心', '基地', '点位']):
        return converter.convert_facility_description(text, context)
    elif any(kw in text for kw in ['发展轴', '发展带', '连接', '轴线']):
        return converter.convert_axis_description(text, context)
    else:
        logger.warning(f"[规划转换] 无法识别描述类型: {text[:50]}")
        return {'type': 'FeatureCollection', 'features': []}


__all__ = [
    'PlanningTextConverter',
    'convert_planning_text_to_geojson',
    'ZoneParsedResult',
    'FacilityParsedResult',
    'Direction',
]