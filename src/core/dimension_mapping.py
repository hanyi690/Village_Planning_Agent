"""
维度依赖映射配置

定义每个规划维度需要哪些现状分析维度的信息，以及详细规划的三层依赖关系。
支持基于波次的动态并行调度。
"""

# ==========================================
# 维度名称映射（现状分析）- 更新为包含内容说明
# ==========================================

ANALYSIS_DIMENSION_NAMES = {
    "location": "区位与对外交通分析",
    "socio_economic": "社会经济分析",
    "villager_wishes": "村民意愿与诉求分析",
    "superior_planning": "上位规划与政策导向分析",
    "natural_environment": "自然环境与生态本底分析",
    "land_use": "土地利用与合规性分析",
    "traffic": "道路交通与街巷空间分析",
    "public_services": "公共服务设施承载力分析",
    "infrastructure": "基础设施现状分析",
    "ecological_green": "生态绿地与开敞空间分析",
    "architecture": "聚落形态与建筑风貌分析",
    "historical_culture": "历史文化与乡愁保护分析"
}


# ==========================================
# 完整的三层依赖关系映射（现状 → 规划思路 → 详细规划）
# ==========================================

# 详细规划维度的完整依赖链定义
# 每个 detailed dimension 的依赖包括：
# - layer1_analyses: 需要的现状分析维度列表
# - layer2_concepts: 需要的规划思路维度列表
# - wave: 执行波次 (1 或 2)
# - depends_on_detailed: 依赖的其他详细规划维度（仅 project_bank）
FULL_DEPENDENCY_CHAIN = {
    "industry": {
        "layer1_analyses": ["socio_economic", "land_use"],
        "layer2_concepts": ["resource_endowment", "development_goals"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "spatial_structure": {
        "layer1_analyses": ["land_use", "superior_planning", "socio_economic", "natural_environment"],
        "layer2_concepts": ["planning_positioning", "planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "land_use_planning": {
        "layer1_analyses": ["land_use", "superior_planning", "natural_environment"],
        "layer2_concepts": ["planning_positioning", "planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "settlement_planning": {
        "layer1_analyses": ["land_use", "architecture", "socio_economic", "villager_wishes"],
        "layer2_concepts": ["planning_positioning", "development_goals"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "traffic": {
        "layer1_analyses": ["location", "traffic", "villager_wishes", "superior_planning"],
        "layer2_concepts": ["planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "public_service": {
        "layer1_analyses": ["public_services", "socio_economic", "villager_wishes"],
        "layer2_concepts": ["development_goals"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "infrastructure": {
        "layer1_analyses": ["infrastructure", "land_use", "villager_wishes"],
        "layer2_concepts": ["development_goals"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "ecological": {
        "layer1_analyses": ["natural_environment", "ecological_green"],
        "layer2_concepts": ["resource_endowment", "planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "disaster_prevention": {
        "layer1_analyses": ["infrastructure", "natural_environment"],
        "layer2_concepts": ["planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "heritage": {
        "layer1_analyses": ["historical_culture"],
        "layer2_concepts": ["planning_positioning"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "landscape": {
        "layer1_analyses": ["architecture"],
        "layer2_concepts": ["planning_positioning", "resource_endowment"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "project_bank": {
        "layer1_analyses": ["land_use", "socio_economic", "location", "villager_wishes", "superior_planning"],
        "layer2_concepts": ["ALL"],  # 需要所有规划思路
        "wave": 2,
        "depends_on_detailed": [
            "industry", "spatial_structure", "land_use_planning", "settlement_planning",
            "traffic", "public_service", "infrastructure", "ecological",
            "disaster_prevention", "heritage", "landscape"
        ]
    }
}


# ==========================================
# 波次配置
# ==========================================

WAVE_CONFIG = {
    1: {
        "dimensions": ["industry", "spatial_structure", "land_use_planning", "settlement_planning",
                      "traffic", "public_service", "infrastructure", "ecological",
                      "disaster_prevention", "heritage", "landscape"],
        "description": "第一波次：11个独立维度完全并行执行"
    },
    2: {
        "dimensions": ["project_bank"],
        "description": "第二波次：项目建设库（等待Wave 1完成）"
    }
}


# ==========================================
# 保留旧映射以保持向后兼容
# ==========================================

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
            "historical_culture",    # 历史文化与乡愁保护
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

def get_concept_to_detailed_mapping(detailed_dimension: str) -> dict:
    """
    从完整依赖链中提取规划思路维度映射（替代旧的 CONCEPT_TO_DETAILED_MAPPING）

    Args:
        detailed_dimension: 详细规划维度

    Returns:
        包含 required_concepts 和 required_analyses 的字典
    """
    chain = FULL_DEPENDENCY_CHAIN.get(detailed_dimension, {})
    return {
        "required_concepts": chain.get("layer2_concepts", []),
        "required_analyses": chain.get("layer1_analyses", [])
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
    "spatial_structure": "空间结构规划",
    "land_use_planning": "土地利用规划",
    "settlement_planning": "居民点规划",
    "traffic": "道路交通规划",
    "public_service": "公服设施规划",
    "infrastructure": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
    "landscape": "村庄风貌指引",
    "project_bank": "建设项目库"
}


# ==========================================
# 新增：依赖查询API
# ==========================================

def get_full_dependency_chain(detailed_dimension: str) -> dict:
    """
    获取指定详细规划维度的完整依赖链

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）

    Returns:
        包含 layer1_analyses, layer2_concepts, wave, depends_on_detailed 的字典
    """
    return FULL_DEPENDENCY_CHAIN.get(detailed_dimension, {})


def get_execution_wave(detailed_dimension: str) -> int:
    """
    获取指定详细规划维度的执行波次

    Args:
        detailed_dimension: 详细规划维度

    Returns:
        波次编号 (1 或 2)，未找到返回 0
    """
    chain = FULL_DEPENDENCY_CHAIN.get(detailed_dimension)
    if chain:
        return chain.get("wave", 0)
    return 0


def get_dimensions_by_wave(wave: int) -> list:
    """
    获取指定波次的所有维度

    Args:
        wave: 波次编号 (1 或 2)

    Returns:
        该波次的维度列表
    """
    config = WAVE_CONFIG.get(wave)
    if config:
        return config.get("dimensions", [])
    return []


def check_detailed_dependencies_ready(dimension: str, completed_dimensions: list) -> bool:
    """
    检查指定详细规划维度的依赖是否满足

    Args:
        dimension: 详细规划维度
        completed_dimensions: 已完成的维度列表

    Returns:
        True 如果依赖满足，False 否则
    """
    chain = FULL_DEPENDENCY_CHAIN.get(dimension)
    if not chain:
        return True  # 未找到依赖信息，默认可以执行

    depends_on = chain.get("depends_on_detailed", [])
    if not depends_on:
        return True  # 无依赖，可以执行

    # 检查所有依赖是否都已完成
    return all(d in completed_dimensions for d in depends_on)


def visualize_dependency_graph() -> str:
    """
    生成依赖关系的 Mermaid 格式图（用于调试和文档）

    Returns:
        Mermaid 格式的依赖图字符串
    """
    lines = ["graph TD"]

    # 添加现状分析节点
    for dim in ANALYSIS_DIMENSION_NAMES.keys():
        lines.append(f"    A1_{dim}[现状: {ANALYSIS_DIMENSION_NAMES[dim]}]")

    # 添加规划思路节点
    for dim in CONCEPT_DIMENSION_NAMES.keys():
        lines.append(f"    A2_{dim}[思路: {CONCEPT_DIMENSION_NAMES[dim]}]")

    # 添加详细规划节点
    for dim in DETAILED_DIMENSION_NAMES.keys():
        wave = get_execution_wave(dim)
        lines.append(f"    A3_{dim}[详细: {DETAILED_DIMENSION_NAMES[dim]} (Wave {wave})]")

    # 添加依赖关系
    for detailed_dim, chain in FULL_DEPENDENCY_CHAIN.items():
        # 现状 -> 详细规划
        for analysis_dim in chain.get("layer1_analyses", []):
            lines.append(f"    A1_{analysis_dim} --> A3_{detailed_dim}")

        # 思路 -> 详细规划
        for concept_dim in chain.get("layer2_concepts", []):
            if concept_dim != "ALL":
                lines.append(f"    A2_{concept_dim} --> A3_{detailed_dim}")

        # 详细规划间依赖
        for dep_dim in chain.get("depends_on_detailed", []):
            lines.append(f"    A3_{dep_dim} -.-> A3_{detailed_dim}")

    return "\n".join(lines)


def get_wave_summary() -> dict:
    """
    获取波次执行摘要

    Returns:
        包含波次信息的字典
    """
    summary = {}
    for wave_num in sorted(WAVE_CONFIG.keys()):
        config = WAVE_CONFIG[wave_num]
        dimensions = config["dimensions"]
        summary[wave_num] = {
            "description": config["description"],
            "dimensions": dimensions,
            "count": len(dimensions),
            "dimension_names": [DETAILED_DIMENSION_NAMES[d] for d in dimensions]
        }
    return summary


# ==========================================
# 统一的维度映射API
# ==========================================

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
    return ["ALL"]


def get_required_info_for_detailed(detailed_dimension: str) -> dict:
    """
    获取指定详细规划维度需要的信息（从 FULL_DEPENDENCY_CHAIN 提取）

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）

    Returns:
        包含 required_concepts 和 required_analyses 的字典
    """
    chain = FULL_DEPENDENCY_CHAIN.get(detailed_dimension)
    if chain:
        return {
            "required_concepts": chain.get("layer2_concepts", []),
            "required_analyses": chain.get("layer1_analyses", [])
        }
    return {
        "required_concepts": ["ALL"],
        "required_analyses": ["ALL"]
    }


# ==========================================
# 默认适配器配置
# ==========================================

DEFAULT_ADAPTER_CONFIG = {
    "industry": ["gis"],
    "spatial_structure": ["gis"],
    "land_use_planning": ["gis"],
    "settlement_planning": ["gis"],
    "ecological": ["gis"],
    "traffic": ["network"],
    "infrastructure": ["gis", "network"],
    "public_service": ["network"],
    "landscape": ["gis"],
    "disaster_prevention": ["gis"]
}


__all__ = [
    "ANALYSIS_DIMENSION_NAMES",
    "CONCEPT_DIMENSION_NAMES",
    "DETAILED_DIMENSION_NAMES",
    "FULL_DEPENDENCY_CHAIN",
    "WAVE_CONFIG",
    "DEFAULT_ADAPTER_CONFIG",
    "get_full_dependency_chain",
    "get_execution_wave",
    "get_dimensions_by_wave",
    "check_detailed_dependencies_ready",
    "visualize_dependency_graph",
    "get_wave_summary",
    "get_required_analyses_for_concept",
    "get_required_info_for_detailed",
]
