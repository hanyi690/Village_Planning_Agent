"""
维度元数据配置

从 dimensions.yaml 迁移到 Python 代码，提供维度的元数据信息。
包括 layer、dependencies、state_filter、rag_enabled、tool 等配置。
"""

from typing import Dict, List, Any, Optional

# ==========================================
# 维度元数据配置
# ==========================================

DIMENSIONS_METADATA: Dict[str, Dict[str, Any]] = {
    # ==========================================
    # Layer 1: 现状分析 (12个)
    # ==========================================
    
    "location": {
        "key": "location",
        "name": "区位与对外交通分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄的地理位置、交通区位、区域关系等",
        "prompt_key": "location_analysis"
    },
    
    "socio_economic": {
        "key": "socio_economic",
        "name": "社会经济分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄人口、经济、产业等社会经济状况",
        "prompt_key": "socio_economic_analysis"
    },
    
    "villager_wishes": {
        "key": "villager_wishes",
        "name": "村民意愿与诉求分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村民对村庄发展的期望、诉求和参与意愿",
        "prompt_key": "villager_wishes_analysis"
    },

    "superior_planning": {
        "key": "superior_planning",
        "name": "上位规划与政策导向分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析上位规划要求、政策约束和发展导向",
        "prompt_key": "superior_planning_analysis"
    },

    "natural_environment": {
        "key": "natural_environment",
        "name": "自然环境分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄的气候、水文、地形、生态等自然环境条件",
        "prompt_key": "natural_environment_analysis"
    },

    "land_use": {
        "key": "land_use",
        "name": "土地利用分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄各类用地的分布、规模和利用效率",
        "prompt_key": "land_use_analysis"
    },
    
    "traffic": {
        "key": "traffic",
        "name": "道路交通分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄内部道路和外部交通状况",
        "prompt_key": "traffic_analysis"
    },

    "public_services": {
        "key": "public_services",
        "name": "公共服务设施分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄教育、医疗、文化等公共服务设施配置",
        "prompt_key": "public_services_analysis"
    },

    "infrastructure": {
        "key": "infrastructure",
        "name": "基础设施分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄供水、供电、排水、通信、环卫等基础设施状况",
        "prompt_key": "infrastructure_analysis"
    },

    "ecological_green": {
        "key": "ecological_green",
        "name": "生态绿地分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄绿地、公园、生态空间等绿色基础设施",
        "prompt_key": "ecological_green_analysis"
    },
    
    "architecture": {
        "key": "architecture",
        "name": "建筑分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄建筑的质量、风格、年代、功能等特征",
        "prompt_key": "architecture_analysis"
    },

    "historical_culture": {
        "key": "historical_culture",
        "name": "历史文化与乡愁保护分析",
        "layer": 1,
        "dependencies": [],
        "state_filter": None,
        "result_key": "analysis_result",
        "rag_enabled": True,
        "tool": None,
        "description": "分析村庄的历史文化遗产、民俗风情、非物质文化、乡愁记忆等",
        "prompt_key": "historical_culture_analysis"
    },
    
    # ==========================================
    # Layer 2: 规划思路 (4个)
    # ==========================================
    
    "resource_endowment": {
        "key": "resource_endowment",
        "name": "资源禀赋分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": [
                "natural_environment",
                "land_use",
                "socio_economic",
                "historical_culture",
                "architecture",
                "public_services"
            ]
        },
        "state_filter": "filter_analysis_report_for_concept",
        "result_key": "concept_result",
        "rag_enabled": False,
        "tool": None,
        "description": "深入挖掘和梳理村庄的资源禀赋",
        "prompt_key": "resource_endowment"
    },

    "planning_positioning": {
        "key": "planning_positioning",
        "name": "规划定位分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": [
                "location",
                "socio_economic",
                "superior_planning"
            ],
            "layer2_concepts": ["resource_endowment"]
        },
        "state_filter": "filter_analysis_report_for_concept",
        "result_key": "concept_result",
        "rag_enabled": False,
        "tool": None,
        "description": "确定村庄的发展定位",
        "prompt_key": "planning_positioning"
    },

    "development_goals": {
        "key": "development_goals",
        "name": "发展目标分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": ["socio_economic", "superior_planning"],
            "layer2_concepts": ["resource_endowment", "planning_positioning"]
        },
        "state_filter": "filter_analysis_report_for_concept",
        "result_key": "concept_result",
        "rag_enabled": False,
        "tool": None,
        "description": "制定简",
        "prompt_key": "development_goals"
    },

    "planning_strategies": {
        "key": "planning_strategies",
        "name": "规划策略分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": [
                "natural_environment",
                "land_use",
                "traffic",
                "infrastructure",
                "historical_culture"
            ],
            "layer2_concepts": [
                "resource_endowment",
                "planning_positioning",
                "development_goals"
            ]
        },
        "state_filter": "filter_analysis_report_for_concept",
        "result_key": "concept_result",
        "rag_enabled": False,
        "tool": None,
        "description": "制定系统性的规划策略",
        "prompt_key": "planning_strategies"
    },
    
    # ==========================================
    # Layer 3: 详细规划 (12个)
    # ==========================================
    
    "industry": {
        "key": "industry",
        "name": "产业规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["socio_economic", "land_use"],
            "layer2_concepts": ["resource_endowment", "planning_positioning", "planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄产业发展规划",
        "prompt_key": "industry"
    },

    "spatial_structure": {
        "key": "spatial_structure",
        "name": "空间结构规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["natural_environment", "land_use", "traffic", "architecture"],
            "layer2_concepts": ["planning_positioning", "planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄空间结构规划方案",
        "prompt_key": "spatial_structure"
    },

    "land_use_planning": {
        "key": "land_use_planning",
        "name": "土地利用规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["land_use", "natural_environment"],
            "layer2_concepts": ["planning_positioning", "planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄土地利用规划方案",
        "prompt_key": "land_use_planning"
    },

    "settlement_planning": {
        "key": "settlement_planning",
        "name": "居民点规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["architecture", "infrastructure", "land_use"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄居民点规划方案",
        "prompt_key": "settlement_planning"
    },
    
    "traffic_planning": {
        "key": "traffic_planning",
        "name": "道路交通规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["traffic", "land_use"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄道路交通系统详细规划",
        "prompt_key": "traffic_planning"
    },

    "public_service": {
        "key": "public_service",
        "name": "公共服务设施规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["public_services", "socio_economic"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄公共服务设施配置规划",
        "prompt_key": "public_service"
    },

    "infrastructure_planning": {
        "key": "infrastructure_planning",
        "name": "基础设施规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["infrastructure", "natural_environment"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄基础设施系统规划",
        "prompt_key": "infrastructure_planning"
    },

    "ecological": {
        "key": "ecological",
        "name": "生态绿地规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["natural_environment", "ecological_green", "land_use"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄生态绿地系统规划",
        "prompt_key": "ecological"
    },
    
    "disaster_prevention": {
        "key": "disaster_prevention",
        "name": "防震减灾规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["natural_environment", "infrastructure"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄防震减灾规划",
        "prompt_key": "disaster_prevention"
    },

    "heritage": {
        "key": "heritage",
        "name": "历史文保规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["historical_culture", "architecture"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄历史文化遗产保护规划",
        "prompt_key": "heritage"
    },

    "landscape": {
        "key": "landscape",
        "name": "村庄风貌指引",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["architecture", "historical_culture", "ecological_green"],
            "layer2_concepts": ["planning_strategies"]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "制定村庄风貌控制和引导规划",
        "prompt_key": "landscape"
    },

    "project_bank": {
        "key": "project_bank",
        "name": "建设项目库",
        "layer": 3,
        "dependencies": {
            "layer3_plans": [
                "industry",
                "spatial_structure",
                "land_use_planning",
                "settlement_planning",
                "traffic_planning",
                "public_service",
                "infrastructure_planning",
                "ecological",
                "disaster_prevention",
                "heritage",
                "landscape"
            ]
        },
        "state_filter": "filter_state_for_detailed_dimension_v2",
        "result_key": "detailed_plan",
        "rag_enabled": False,
        "tool": None,
        "description": "整合各专业规划，建立建设项目库",
        "prompt_key": "project_bank"
    }
}


# ==========================================
# 辅助函数
# ==========================================

def get_dimension_config(dimension_key: str) -> Optional[Dict[str, Any]]:
    """
    获取指定维度的配置
    
    Args:
        dimension_key: 维度键名
    
    Returns:
        维度配置字典，如果不存在则返回 None
    """
    return DIMENSIONS_METADATA.get(dimension_key)


def list_dimensions(layer: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    列出维度
    
    Args:
        layer: 可选，筛选指定层的维度（1, 2, 或 3）
    
    Returns:
        维度配置列表
    """
    if layer is None:
        return list(DIMENSIONS_METADATA.values())
    
    return [
        config for config in DIMENSIONS_METADATA.values()
        if config.get("layer") == layer
    ]


def get_layer_dimensions(layer: int) -> List[str]:
    """
    获取指定层的所有维度键名
    
    Args:
        layer: 层级（1, 2, 或 3）
    
    Returns:
        维度键名列表
    """
    return [
        config["key"] for config in DIMENSIONS_METADATA.values()
        if config.get("layer") == layer
    ]


def get_dimension_layer(dimension_key: str) -> Optional[int]:
    """
    获取维度所属的层级
    
    Args:
        dimension_key: 维度键名
    
    Returns:
        层级（1, 2, 或 3），如果不存在则返回 None
    """
    config = get_dimension_config(dimension_key)
    return config.get("layer") if config else None


def dimension_exists(dimension_key: str) -> bool:
    """
    检查维度是否存在
    
    Args:
        dimension_key: 维度键名
    
    Returns:
        如果存在返回 True，否则返回 False
    """
    return dimension_key in DIMENSIONS_METADATA


# ==========================================
# 导出
# ==========================================

__all__ = [
    "DIMENSIONS_METADATA",
    "get_dimension_config",
    "list_dimensions",
    "get_layer_dimensions",
    "get_dimension_layer",
    "dimension_exists",
]