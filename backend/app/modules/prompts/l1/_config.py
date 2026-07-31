"""L1 维度元数据 - 哪个维度提取哪类实体。"""

DIMENSION_NAMES = {
    "location": "区位与对外交通分析",
    "socio_economic": "社会经济分析",
    "villager_wishes": "村民意愿分析",
    "superior_planning": "上位规划分析",
    "natural_environment": "自然环境分析",
    "land_use": "土地利用分析",
    "traffic": "道路交通分析",
    "public_services": "公共服务设施分析",
    "infrastructure": "基础设施分析",
    "ecological_green": "生态绿地分析",
    "architecture": "建筑风貌分析",
    "historical_culture": "历史文化分析",
}

DIMENSION_CONFIG = {
    "location": {"entity_types": [], "output_kind": "narrative"},
    "socio_economic": {"entity_types": [], "output_kind": "narrative"},
    "villager_wishes": {"entity_types": [], "output_kind": "narrative"},
    "superior_planning": {"entity_types": [], "output_kind": "narrative"},
    "natural_environment": {"entity_types": ["water", "control_line"], "output_kind": "narrative_with_entities"},
    "land_use": {"entity_types": ["parcel"], "output_kind": "narrative_with_entities"},
    "traffic": {"entity_types": ["road", "facility"], "output_kind": "narrative_with_entities"},
    "public_services": {"entity_types": ["facility"], "output_kind": "narrative_with_entities"},
    "infrastructure": {"entity_types": ["facility", "control_line"], "output_kind": "narrative_with_entities"},
    "ecological_green": {"entity_types": ["control_line", "parcel"], "output_kind": "narrative_with_entities"},
    "architecture": {"entity_types": ["building"], "output_kind": "narrative_with_entities"},
    "historical_culture": {"entity_types": ["historical_site", "building"], "output_kind": "narrative_with_entities"},
}

__all__ = ["DIMENSION_NAMES", "DIMENSION_CONFIG"]
