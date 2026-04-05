"""
维度元数据配置

从 dimensions.yaml 迁移到 Python 代码，提供维度的元数据信息。
包括 layer、dependencies、state_filter、rag_enabled、tool 等配置。

注意：
- state_filter 字段已废弃（原计划用于动态筛选函数，但未实现）
- 实际筛选逻辑已硬编码在 dimension_node.py 的 _build_dimension_prompt 函数中
- 保留 state_filter 作为文档标记，用于说明预期的筛选意图
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
        "tool": "population_model_v1",  # 人口预测工具，提供人口趋势分析
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
        "tool": "wfs_data_fetch",  # WFS 数据获取工具，获取水系/地形数据
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
        "tool": "gis_coverage_calculator",  # GIS 覆盖率计算工具，提供土地利用结构分析
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
        "tool": "accessibility_analysis",  # 可达性分析工具，基于真实道路网络
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
        "tool": "poi_search",  # POI 搜索工具，获取公共服务设施分布
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
        "description": "制定一句简洁的语句",
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
        "rag_enabled": True,  # 关键维度：涉及法规条文和技术指标
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
        "rag_enabled": True,  # 关键维度：涉及技术规范和标准
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
        "rag_enabled": True,  # 关键维度：涉及生态保护法规
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
        "rag_enabled": True,  # 关键维度：涉及安全规范和强制标准
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
        "rag_enabled": True,  # 关键维度：涉及文物保护法规
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
# 缓存变量（延迟加载）
# ==========================================

_ANALYSIS_DIMENSION_NAMES = None
_CONCEPT_DIMENSION_NAMES = None
_DETAILED_DIMENSION_NAMES = None
_ANALYSIS_TO_CONCEPT_MAPPING = None
_CONCEPT_TO_DETAILED_MAPPING = None
_FULL_DEPENDENCY_CHAIN = None
_WAVE_CONFIG = None


# ==========================================
# 名称映射函数
# ==========================================

def get_analysis_dimension_names() -> Dict[str, str]:
    """获取现状分析维度名称映射 (key -> name)"""
    global _ANALYSIS_DIMENSION_NAMES
    if _ANALYSIS_DIMENSION_NAMES is None:
        _ANALYSIS_DIMENSION_NAMES = {
            key: config["name"]
            for key, config in DIMENSIONS_METADATA.items()
            if config.get("layer") == 1
        }
    return _ANALYSIS_DIMENSION_NAMES


def get_concept_dimension_names() -> Dict[str, str]:
    """获取规划思路维度名称映射 (key -> name)"""
    global _CONCEPT_DIMENSION_NAMES
    if _CONCEPT_DIMENSION_NAMES is None:
        _CONCEPT_DIMENSION_NAMES = {
            key: config["name"]
            for key, config in DIMENSIONS_METADATA.items()
            if config.get("layer") == 2
        }
    return _CONCEPT_DIMENSION_NAMES


def get_detailed_dimension_names() -> Dict[str, str]:
    """获取详细规划维度名称映射 (key -> name)"""
    global _DETAILED_DIMENSION_NAMES
    if _DETAILED_DIMENSION_NAMES is None:
        _DETAILED_DIMENSION_NAMES = {
            key: config["name"]
            for key, config in DIMENSIONS_METADATA.items()
            if config.get("layer") == 3
        }
    return _DETAILED_DIMENSION_NAMES


# 直接访问变量（兼容旧代码）
ANALYSIS_DIMENSION_NAMES = property(get_analysis_dimension_names)
CONCEPT_DIMENSION_NAMES = property(get_concept_dimension_names)
DETAILED_DIMENSION_NAMES = property(get_detailed_dimension_names)


# ==========================================
# 依赖映射函数
# ==========================================

def get_analysis_to_concept_mapping() -> Dict[str, List[str]]:
    """
    获取现状分析到规划思路的映射
    
    Returns:
        {concept_dimension: [analysis_dimensions]}
    """
    global _ANALYSIS_TO_CONCEPT_MAPPING
    if _ANALYSIS_TO_CONCEPT_MAPPING is None:
        mapping = {}
        for key, config in DIMENSIONS_METADATA.items():
            if config.get("layer") == 2:
                deps = config.get("dependencies", {})
                mapping[key] = deps.get("layer1_analyses", [])
        _ANALYSIS_TO_CONCEPT_MAPPING = mapping
    return _ANALYSIS_TO_CONCEPT_MAPPING


def get_concept_to_detailed_mapping() -> Dict[str, List[str]]:
    """
    获取规划思路到详细规划的映射
    
    Returns:
        {detailed_dimension: [concept_dimensions]}
    """
    global _CONCEPT_TO_DETAILED_MAPPING
    if _CONCEPT_TO_DETAILED_MAPPING is None:
        mapping = {}
        for key, config in DIMENSIONS_METADATA.items():
            if config.get("layer") == 3:
                deps = config.get("dependencies", {})
                mapping[key] = deps.get("layer2_concepts", [])
        _CONCEPT_TO_DETAILED_MAPPING = mapping
    return _CONCEPT_TO_DETAILED_MAPPING


# 直接访问变量
ANALYSIS_TO_CONCEPT_MAPPING = property(get_analysis_to_concept_mapping)
CONCEPT_TO_DETAILED_MAPPING = property(get_concept_to_detailed_mapping)


# ==========================================
# 完整依赖链
# ==========================================

def get_full_dependency_chain() -> Dict[str, Dict[str, Any]]:
    """
    获取完整的三层依赖关系映射
    
    自动计算 wave 值：基于同层内部依赖关系拓扑排序
    
    Returns:
        {dimension_key: {layer1_analyses: [...], layer2_concepts: [...], wave: N, depends_on_same_layer: [...]}}
    """
    global _FULL_DEPENDENCY_CHAIN
    if _FULL_DEPENDENCY_CHAIN is None:
        chain = {}
        
        # 收集所有维度的依赖信息
        for key, config in DIMENSIONS_METADATA.items():
            layer = config.get("layer")
            deps = config.get("dependencies", {})
            
            if layer == 3:
                # Layer 3: 检查同层依赖 (layer3_plans)
                depends_on_same_layer = deps.get("layer3_plans", [])
            elif layer == 2:
                # Layer 2: 检查同层依赖 (layer2_concepts)
                depends_on_same_layer = deps.get("layer2_concepts", [])
            else:
                depends_on_same_layer = []
            
            chain[key] = {
                "layer": layer,
                "layer1_analyses": deps.get("layer1_analyses", []) if layer >= 2 else [],
                "layer2_concepts": deps.get("layer2_concepts", []) if layer == 3 else [],
                "layer3_plans": deps.get("layer3_plans", []) if layer == 3 else [],
                "depends_on_same_layer": depends_on_same_layer,
                "wave": 1  # 默认值，后续自动计算
            }
        
        # 自动计算每个维度的 wave（拓扑排序）
        for key in chain:
            chain[key]["wave"] = _calculate_wave(key, chain)
        
        _FULL_DEPENDENCY_CHAIN = chain
    return _FULL_DEPENDENCY_CHAIN


def _calculate_wave(dimension_key: str, chain: Dict[str, Dict[str, Any]]) -> int:
    """
    递归计算维度的执行波次
    
    Wave = 1 + max(wave of dependencies within same layer)
    
    Args:
        dimension_key: 维度键名
        chain: 完整依赖链
        
    Returns:
        执行波次（从1开始）
    """
    if dimension_key not in chain:
        return 1
    
    deps = chain[dimension_key]
    same_layer_deps = deps.get("depends_on_same_layer", [])
    
    if not same_layer_deps:
        return 1
    
    # 递归计算依赖的 wave
    max_dep_wave = 0
    for dep_key in same_layer_deps:
        if dep_key in chain:
            dep_wave = chain[dep_key].get("wave", 1)
            if dep_wave == 1:
                # 依赖的 wave 还没计算，递归计算
                dep_wave = _calculate_wave(dep_key, chain)
                chain[dep_key]["wave"] = dep_wave
            max_dep_wave = max(max_dep_wave, dep_wave)
    
    return max_dep_wave + 1


def get_full_dependency_chain_func(dimension_key: str) -> Dict[str, Any]:
    """
    获取单个维度的依赖链
    
    Args:
        dimension_key: 维度键名
        
    Returns:
        依赖链字典，如果不存在返回空字典
    """
    chain = get_full_dependency_chain()
    return chain.get(dimension_key, {})


FULL_DEPENDENCY_CHAIN = property(get_full_dependency_chain)


# ==========================================
# 波次配置
# ==========================================

def get_wave_config() -> Dict[int, Dict[str, Any]]:
    """
    获取波次配置（自动计算）
    
    Returns:
        {wave_number: {dimensions: [...], description: "..."}}
    """
    global _WAVE_CONFIG
    if _WAVE_CONFIG is None:
        chain = get_full_dependency_chain()
        waves = {}
        
        for key, deps in chain.items():
            wave = deps.get("wave", 1)
            layer = deps.get("layer", 1)
            
            # 只为 Layer 2 和 Layer 3 生成波次配置
            if layer >= 2:
                if wave not in waves:
                    waves[wave] = {
                        "dimensions": [],
                        "description": f"Wave {wave}"
                    }
                waves[wave]["dimensions"].append(key)
        
        # 添加描述
        for wave_num in sorted(waves.keys()):
            if wave_num == 1:
                waves[wave_num]["description"] = f"第一波次：{len(waves[wave_num]['dimensions'])}个独立维度并行执行"
            else:
                waves[wave_num]["description"] = f"第{wave_num}波次：依赖前序波次的维度"
        
        _WAVE_CONFIG = waves
    return _WAVE_CONFIG


def get_execution_wave(dimension_key: str) -> int:
    """获取维度所属的执行波次"""
    chain = get_full_dependency_chain()
    if dimension_key in chain:
        return chain[dimension_key].get("wave", 1)
    return 1


def get_dimensions_by_wave(wave: int, layer: Optional[int] = None) -> List[str]:
    """
    获取指定波次的所有维度
    
    Args:
        wave: 波次号
        layer: 可选，筛选特定层级
        
    Returns:
        维度键名列表
    """
    chain = get_full_dependency_chain()
    result = []
    
    for key, deps in chain.items():
        if deps.get("wave") == wave:
            if layer is None or deps.get("layer") == layer:
                result.append(key)
    
    return result


def check_detailed_dependencies_ready(
    dimension_key: str,
    completed_dimensions: List[str]
) -> bool:
    """
    检查详细规划维度的依赖是否就绪
    
    Args:
        dimension_key: 详细规划维度键名
        completed_dimensions: 已完成的维度列表
        
    Returns:
        如果所有依赖都已就绪返回 True
    """
    chain = get_full_dependency_chain()
    if dimension_key not in chain:
        return True
    
    deps = chain[dimension_key]
    completed_set = set(completed_dimensions)
    
    # 检查 Layer 1 依赖
    for dep in deps.get("layer1_analyses", []):
        if dep not in completed_set:
            return False
    
    # 检查 Layer 2 依赖
    for dep in deps.get("layer2_concepts", []):
        if dep not in completed_set:
            return False
    
    # 检查详细规划内部依赖
    for dep in deps.get("depends_on_detailed", []):
        if dep not in completed_set:
            return False
    
    return True


# 缓存下游依赖映射
_DOWNSTREAM_DEPENDENCIES_CACHE = None


def get_downstream_dependencies(dimension_key: str) -> List[str]:
    """
    获取依赖指定维度的所有下游维度（反向依赖）
    
    用于维度修复时确定需要级联更新的下游维度。
    
    Args:
        dimension_key: 维度键名
        
    Returns:
        依赖该维度的下游维度列表
    """
    global _DOWNSTREAM_DEPENDENCIES_CACHE
    
    # 构建缓存
    if _DOWNSTREAM_DEPENDENCIES_CACHE is None:
        cache = {}
        for key, config in DIMENSIONS_METADATA.items():
            deps = config.get("dependencies", {})
            
            # 处理 dependencies 是列表的情况（Layer 1 维度）
            if isinstance(deps, list):
                continue
            
            # 处理 Layer 1 依赖
            for dep in deps.get("layer1_analyses", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)
            
            # 处理 Layer 2 依赖
            for dep in deps.get("layer2_concepts", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)
            
            # 处理 Layer 3 依赖（同层依赖）
            for dep in deps.get("layer3_plans", []):
                if dep not in cache:
                    cache[dep] = []
                cache[dep].append(key)
        
        _DOWNSTREAM_DEPENDENCIES_CACHE = cache
    
    return _DOWNSTREAM_DEPENDENCIES_CACHE.get(dimension_key, [])


WAVE_CONFIG = property(get_wave_config)


# ==========================================
# 影响树（用于 Revision 级联更新）
# ==========================================

_IMPACT_TREE_CACHE = None


def get_impact_tree(dimension_key: str) -> Dict[int, List[str]]:
    """
    获取维度修改后的影响树（级联更新范围）
    
    当一个维度被修改后，需要级联更新所有依赖它的下游维度。
    返回按 wave 分组的维度列表，支持并行调度：
    - Wave 1: 直接依赖该维度的下游维度（可并行）
    - Wave 2: 依赖 Wave 1 维度的下游维度（可并行）
    - ...
    
    Args:
        dimension_key: 维度键名
        
    Returns:
        {wave: [dimension_keys]} 按 wave 分组的维度列表
        
    Example:
        >>> get_impact_tree("natural_environment")
        {
            1: ["resource_endowment", "ecological", "spatial_structure", "land_use_planning", "disaster_prevention"],
            2: ["planning_positioning", "planning_strategies"],
            3: ["development_goals", "project_bank"]
        }
    """
    global _IMPACT_TREE_CACHE
    
    # 构建缓存（所有维度的影响树）
    if _IMPACT_TREE_CACHE is None:
        _IMPACT_TREE_CACHE = _build_all_impact_trees()
    
    return _IMPACT_TREE_CACHE.get(dimension_key, {})


def _build_all_impact_trees() -> Dict[str, Dict[int, List[str]]]:
    """
    构建所有维度的影响树缓存
    
    Returns:
        {dimension_key: {wave: [dependent_dimensions]}}
    """
    chain = get_full_dependency_chain()
    trees = {}
    
    # 对每个维度，递归计算其影响范围
    for dim_key in DIMENSIONS_METADATA.keys():
        trees[dim_key] = _calculate_impact_tree(dim_key, chain)
    
    return trees


def _calculate_impact_tree(
    dimension_key: str,
    chain: Dict[str, Dict[str, Any]]
) -> Dict[int, List[str]]:
    """
    计算单个维度的影响树
    
    使用 BFS 遍历下游依赖，按 wave 分组
    
    Args:
        dimension_key: 维度键名
        chain: 完整依赖链
        
    Returns:
        {wave: [dimension_keys]}
    """
    impact_tree: Dict[int, List[str]] = {}
    visited = {dimension_key}  # 避免循环
    current_wave_dims = [dimension_key]
    wave = 0
    
    while current_wave_dims:
        # 获取当前 wave 所有维度的直接下游依赖
        next_wave_dims = []
        for dim in current_wave_dims:
            downstream = get_downstream_dependencies(dim)
            for dep_dim in downstream:
                if dep_dim not in visited:
                    visited.add(dep_dim)
                    next_wave_dims.append(dep_dim)
        
        if next_wave_dims:
            wave += 1
            # 按 wave 重新分组（基于维度自身的 wave 属性）
            impact_tree[wave] = next_wave_dims
        
        current_wave_dims = next_wave_dims
    
    # 对每个 wave 内的维度按其自身 wave 属性排序（确保执行顺序正确）
    sorted_tree = {}
    for w, dims in impact_tree.items():
        # 过滤掉不存在的维度，并按维度自身的 wave 排序
        valid_dims = [d for d in dims if d in chain]
        sorted_dims = sorted(valid_dims, key=lambda d: chain[d].get("wave", 1))
        if sorted_dims:
            sorted_tree[w] = sorted_dims
    
    return sorted_tree


def get_revision_wave_dimensions(
    target_dimensions: List[str],
    completed_dimensions: List[str]
) -> Dict[int, List[str]]:
    """
    获取修复任务中当前可执行的维度（按 wave 分组）
    
    合并多个目标维度的影响树，过滤已完成的维度，返回待执行的维度。
    
    Args:
        target_dimensions: 用户选择要修复的维度列表
        completed_dimensions: 已完成的维度列表（用于过滤）
        
    Returns:
        {wave: [dimension_keys]} 可并行执行的维度分组
    """
    completed_set = set(completed_dimensions)
    all_impact_dims: Dict[str, int] = {}  # {dimension: min_wave}
    
    # 合并所有目标维度的影响树
    for target_dim in target_dimensions:
        # 目标维度自身属于 Wave 0
        if target_dim not in all_impact_dims:
            all_impact_dims[target_dim] = 0
        
        # 获取下游影响
        impact_tree = get_impact_tree(target_dim)
        for wave, dims in impact_tree.items():
            for dim in dims:
                if dim not in all_impact_dims:
                    all_impact_dims[dim] = wave
                else:
                    # 取最小 wave（确保依赖满足）
                    all_impact_dims[dim] = min(all_impact_dims[dim], wave)
    
    # 只保留已完成的维度（有报告的维度才能被修复）
    # 未完成的维度没有内容可修复，应被过滤掉
    pending_dims = {dim: wave for dim, wave in all_impact_dims.items() 
                    if dim in completed_set}
    
    # 按 wave 分组
    result: Dict[int, List[str]] = {}
    for dim, wave in pending_dims.items():
        if wave not in result:
            result[wave] = []
        result[wave].append(dim)
    
    # 对每个 wave 内部按维度自身的 wave 属性排序
    chain = get_full_dependency_chain()
    for w in result:
        result[w] = sorted(result[w], key=lambda d: chain.get(d, {}).get("wave", 1))
    
    return result


# ==========================================
# 报告筛选辅助函数
# ==========================================

def filter_reports_by_dependency(
    required_keys: List[str],
    reports: Dict[str, str],
    name_mapping: Dict[str, str]
) -> str:
    """
    按依赖配置筛选报告并格式化为 Markdown

    用于 dimension_node 和 revision_node 中统一处理报告筛选逻辑。

    Args:
        required_keys: 需要包含的维度键名列表（来自依赖配置）
        reports: 报告内容字典 {key: content}
        name_mapping: 维度名称映射 {key: display_name}

    Returns:
        格式化的 Markdown 字符串，每个报告为一个章节
    """
    filtered_parts = []
    for k in required_keys:
        if k in reports:
            name = name_mapping.get(k, k)
            filtered_parts.append(f"### {name}\n\n{reports[k]}\n")
    return "\n".join(filtered_parts) if filtered_parts else ""


# ==========================================
# 导出
# ==========================================

__all__ = [
    # 核心数据
    "DIMENSIONS_METADATA",
    
    # 基础函数
    "get_dimension_config",
    "list_dimensions",
    "get_layer_dimensions",
    "get_dimension_layer",
    "dimension_exists",
    
    # 名称映射
    "get_analysis_dimension_names",
    "get_concept_dimension_names",
    "get_detailed_dimension_names",
    "ANALYSIS_DIMENSION_NAMES",
    "CONCEPT_DIMENSION_NAMES",
    "DETAILED_DIMENSION_NAMES",
    
    # 依赖映射
    "get_analysis_to_concept_mapping",
    "get_concept_to_detailed_mapping",
    "ANALYSIS_TO_CONCEPT_MAPPING",
    "CONCEPT_TO_DETAILED_MAPPING",
    
    # 完整依赖链
    "get_full_dependency_chain",
    "get_full_dependency_chain_func",
    "FULL_DEPENDENCY_CHAIN",
    
    # 波次配置
    "get_wave_config",
    "get_execution_wave",
    "get_dimensions_by_wave",
    "check_detailed_dependencies_ready",
    "WAVE_CONFIG",
    
    # 下游依赖
    "get_downstream_dependencies",
    
    # 影响树（用于 Revision）
    "get_impact_tree",
    "get_revision_wave_dimensions",

    # 报告筛选辅助
    "filter_reports_by_dependency",
]