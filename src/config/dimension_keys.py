"""
维度键名枚举

统一管理所有维度的键名，避免硬编码，确保一致性。
"""

from enum import Enum


class DimensionKey(str, Enum):
    """
    维度键名枚举
    
    继承 str 使其可直接用于字符串比较和字典键
    """
    
    # ==========================================
    # Layer 1: 现状分析 (12个)
    # ==========================================
    
    LOCATION = "location"                       # 区位与对外交通分析
    SOCIO_ECONOMIC = "socio_economic"           # 社会经济分析
    VILLAGER_WISHES = "villager_wishes"         # 村民意愿与诉求分析
    SUPERIOR_PLANNING = "superior_planning"     # 上位规划与政策导向分析
    NATURAL_ENVIRONMENT = "natural_environment" # 自然环境分析
    LAND_USE = "land_use"                       # 土地利用分析
    TRAFFIC = "traffic"                         # 道路交通分析
    PUBLIC_SERVICES = "public_services"         # 公共服务设施分析
    INFRASTRUCTURE = "infrastructure"           # 基础设施分析
    ECOLOGICAL_GREEN = "ecological_green"       # 生态绿地分析
    ARCHITECTURE = "architecture"               # 建筑分析
    HISTORICAL_CULTURE = "historical_culture"   # 历史文化与乡愁保护分析
    
    # ==========================================
    # Layer 2: 规划思路 (4个)
    # ==========================================
    
    RESOURCE_ENDOWMENT = "resource_endowment"       # 资源禀赋分析
    PLANNING_POSITIONING = "planning_positioning"   # 规划定位分析
    DEVELOPMENT_GOALS = "development_goals"         # 发展目标分析
    PLANNING_STRATEGIES = "planning_strategies"     # 规划策略分析
    
    # ==========================================
    # Layer 3: 详细规划 (12个)
    # ==========================================
    
    INDUSTRY = "industry"                           # 产业规划
    SPATIAL_STRUCTURE = "spatial_structure"         # 空间结构规划
    LAND_USE_PLANNING = "land_use_planning"         # 土地利用规划
    SETTLEMENT_PLANNING = "settlement_planning"     # 居民点规划
    TRAFFIC_PLANNING = "traffic_planning"           # 道路交通规划
    PUBLIC_SERVICE = "public_service"               # 公共服务设施规划
    INFRASTRUCTURE_PLANNING = "infrastructure_planning"  # 基础设施规划
    ECOLOGICAL = "ecological"                       # 生态绿地规划
    DISASTER_PREVENTION = "disaster_prevention"     # 防震减灾规划
    HERITAGE = "heritage"                           # 历史文保规划
    LANDSCAPE = "landscape"                         # 村庄风貌指引
    PROJECT_BANK = "project_bank"                   # 建设项目库


# ==========================================
# 按层级分组
# ==========================================

LAYER1_DIMENSIONS = [
    DimensionKey.LOCATION,
    DimensionKey.SOCIO_ECONOMIC,
    DimensionKey.VILLAGER_WISHES,
    DimensionKey.SUPERIOR_PLANNING,
    DimensionKey.NATURAL_ENVIRONMENT,
    DimensionKey.LAND_USE,
    DimensionKey.TRAFFIC,
    DimensionKey.PUBLIC_SERVICES,
    DimensionKey.INFRASTRUCTURE,
    DimensionKey.ECOLOGICAL_GREEN,
    DimensionKey.ARCHITECTURE,
    DimensionKey.HISTORICAL_CULTURE,
]

LAYER2_DIMENSIONS = [
    DimensionKey.RESOURCE_ENDOWMENT,
    DimensionKey.PLANNING_POSITIONING,
    DimensionKey.DEVELOPMENT_GOALS,
    DimensionKey.PLANNING_STRATEGIES,
]

LAYER3_DIMENSIONS = [
    DimensionKey.INDUSTRY,
    DimensionKey.SPATIAL_STRUCTURE,
    DimensionKey.LAND_USE_PLANNING,
    DimensionKey.SETTLEMENT_PLANNING,
    DimensionKey.TRAFFIC_PLANNING,
    DimensionKey.PUBLIC_SERVICE,
    DimensionKey.INFRASTRUCTURE_PLANNING,
    DimensionKey.ECOLOGICAL,
    DimensionKey.DISASTER_PREVENTION,
    DimensionKey.HERITAGE,
    DimensionKey.LANDSCAPE,
    DimensionKey.PROJECT_BANK,
]


def get_layer(dimension_key: str) -> int:
    """
    获取维度所属层级
    
    Args:
        dimension_key: 维度键名
        
    Returns:
        层级号 (1, 2, 或 3)，如果不存在返回 0
    """
    if dimension_key in [d.value for d in LAYER1_DIMENSIONS]:
        return 1
    elif dimension_key in [d.value for d in LAYER2_DIMENSIONS]:
        return 2
    elif dimension_key in [d.value for d in LAYER3_DIMENSIONS]:
        return 3
    return 0


def is_valid_dimension(dimension_key: str) -> bool:
    """
    检查维度键名是否有效
    
    Args:
        dimension_key: 维度键名
        
    Returns:
        是否有效
    """
    try:
        DimensionKey(dimension_key)
        return True
    except ValueError:
        return False


__all__ = [
    "DimensionKey",
    "LAYER1_DIMENSIONS",
    "LAYER2_DIMENSIONS",
    "LAYER3_DIMENSIONS",
    "get_layer",
    "is_valid_dimension",
]
