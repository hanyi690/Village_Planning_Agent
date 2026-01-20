"""
维度依赖映射配置

定义每个规划维度需要哪些现状分析维度的信息。
"""

# 现状分析维度 → 规划思路维度的映射
ANALYSIS_TO_CONCEPT_MAPPING = {
    "resource_endowment": {
        "required_analyses": [
            "natural_environment",   # 自然环境
            "land_use",              # 土地利用
            "ecological_green",      # 生态绿地
            "socio_economic"         # 社会经济（资源禀赋）
        ],
        "description": "资源禀赋分析需要自然资源和土地利用信息"
    },
    "planning_positioning": {
        "required_analyses": [
            "location",              # 区位分析
            "socio_economic",        # 社会经济
            "historical_cultural",   # 历史文化
            "traffic"                # 交通条件
        ],
        "description": "规划定位分析需要区位和人文信息"
    },
    "development_goals": {
        "required_analyses": [
            "socio_economic",        # 社会经济
            "public_services",       # 公共服务
            "infrastructure",        # 基础设施
            "traffic"                # 交通
        ],
        "description": "发展目标分析需要社会服务设施信息"
    },
    "planning_strategies": {
        "required_analyses": [
            # 策略需要综合信息，标记为 "ALL"
            "ALL"  # 特殊标记，表示需要所有维度
        ],
        "description": "规划策略需要全面的现状信息"
    }
}

# 规划思路维度 → 详细规划维度的映射
CONCEPT_TO_DETAILED_MAPPING = {
    "industry": {
        "required_concepts": ["resource_endowment", "development_goals"],
        "required_analyses": ["socio_economic", "land_use"],
        "description": "产业规划需要资源禀赋和发展目标信息"
    },
    "master_plan": {
        "required_concepts": ["planning_positioning", "planning_strategies"],
        "required_analyses": ["ALL"],
        "description": "总体规划需要全面的定位和策略信息"
    },
    "traffic": {
        "required_concepts": ["planning_strategies"],
        "required_analyses": ["traffic", "location", "land_use"],
        "description": "道路交通规划需要交通现状和土地利用信息"
    },
    "public_service": {
        "required_concepts": ["development_goals"],
        "required_analyses": ["public_services", "location", "socio_economic"],
        "description": "公共服务设施规划需要服务现状和人口信息"
    },
    "infrastructure": {
        "required_concepts": ["development_goals"],
        "required_analyses": ["infrastructure", "land_use", "socio_economic"],
        "description": "基础设施规划需要设施现状和布局信息"
    },
    "ecological": {
        "required_concepts": ["resource_endowment", "planning_strategies"],
        "required_analyses": ["ecological_green", "natural_environment", "land_use"],
        "description": "生态绿地规划需要生态现状和自然资源信息"
    },
    "disaster_prevention": {
        "required_concepts": ["planning_strategies"],
        "required_analyses": ["infrastructure", "natural_environment", "architecture"],
        "description": "防震减灾规划需要设施和建筑现状信息"
    },
    "heritage": {
        "required_concepts": ["planning_positioning"],
        "required_analyses": ["historical_cultural", "architecture"],
        "description": "历史文保规划需要历史文化和建筑信息"
    },
    "landscape": {
        "required_concepts": ["planning_positioning", "resource_endowment"],
        "required_analyses": ["architecture", "natural_environment", "ecological_green"],
        "description": "村庄风貌指引需要建筑和自然环境信息"
    },
    "project_bank": {
        "required_concepts": ["ALL"],  # 需要所有规划思路
        "required_analyses": ["ALL"],  # 需要所有现状分析
        "description": "建设项目库需要所有维度的综合信息"
    }
}

# 维度名称映射（现状分析）
ANALYSIS_DIMENSION_NAMES = {
    "location": "区位分析",
    "socio_economic": "社会经济分析",
    "natural_environment": "自然环境分析",
    "land_use": "土地利用分析",
    "traffic": "道路交通分析",
    "public_services": "公共服务设施分析",
    "infrastructure": "基础设施分析",
    "ecological_green": "生态绿地分析",
    "architecture": "建筑分析",
    "historical_cultural": "历史文化分析"
}

# 维度名称映射（规划思路）
CONCEPT_DIMENSION_NAMES = {
    "resource_endowment": "资源禀赋分析",
    "planning_positioning": "规划定位分析",
    "development_goals": "发展目标分析",
    "planning_strategies": "规划策略分析"
}

# 维度名称映射（详细规划）
DETAILED_DIMENSION_NAMES = {
    "industry": "产业规划",
    "master_plan": "村庄总体规划",
    "traffic": "道路交通规划",
    "public_service": "公服设施规划",
    "infrastructure": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
    "landscape": "村庄风貌指引",
    "project_bank": "建设项目库"
}


def get_required_analyses_for_concept(concept_dimension: str) -> list:
    """
    获取指定规划思路维度需要的现状分析维度列表

    Args:
        concept_dimension: 规划思路维度（如 "resource_endowment"）

    Returns:
        需要的现状分析维度列表，如果需要所有维度则返回 ["ALL"]
    """
    mapping = ANALYSIS_TO_CONCEPT_MAPPING.get(concept_dimension)
    if mapping:
        return mapping["required_analyses"]
    # 默认返回所有维度
    return ["ALL"]


def get_required_info_for_detailed(detailed_dimension: str) -> dict:
    """
    获取指定详细规划维度需要的信息

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）

    Returns:
        包含 required_concepts 和 required_analyses 的字典
    """
    mapping = CONCEPT_TO_DETAILED_MAPPING.get(detailed_dimension)
    if mapping:
        return {
            "required_concepts": mapping["required_concepts"],
            "required_analyses": mapping["required_analyses"]
        }
    # 默认返回所有信息
    return {
        "required_concepts": ["ALL"],
        "required_analyses": ["ALL"]
    }
