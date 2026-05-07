"""
RAG Query Builder

提供结构化的 RAG 查询构建功能：
- 特征槽枚举化：避免文学性描述引入噪声
- Layer 1/Layer 3 模板分野：诊断型 vs 规范型
- 模块化设计：便于单元测试和未来扩展
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

# Import from authoritative source
from ...config.dimension_metadata import get_dimension_name

# ==========================================
# 特征槽定义（可枚举）
# ==========================================

FEATURE_SLOTS = {
    "geo_location": ["山区", "平原", "丘陵", "近郊", "远郊", "沿海"],
    "sensitive_attr": ["历史文化名村", "水源保护区", "地震带", "地质灾害区", "生态红线区"],
    "population_feature": ["空心化", "老龄化", "人口流入", "资源枯竭型"],
    "economic_type": ["农业主导", "工业主导", "旅游主导", "综合发展"],
}


@dataclass
class VillageFeatures:
    """村庄特征槽（结构化）"""
    geo_location: Optional[str] = None
    sensitive_attr: List[str] = field(default_factory=list)
    population_feature: Optional[str] = None
    economic_type: Optional[str] = None


class RAGQueryBuilder:
    """RAG 查询构建器"""

    # Layer 1 诊断型模板
    LAYER1_TEMPLATE = (
        "已知村庄特征：{features_summary}。"
        "当前分析维度：{dimension_name}。"
        "请提供对该现状进行优劣势判定的关键指标和底线要求。"
    )

    # Layer 3 规范型模板
    LAYER3_TEMPLATE = (
        "已知村庄特征：{features_summary}，"
        "规划定位：{layer2_summary}。"
        "当前规划维度：{dimension_name}。"
        "请提供强制性技术标准和常用设计参数。"
    )

    def extract_features(self, village_profile: str) -> VillageFeatures:
        """从原始描述中提取结构化特征槽"""
        features = VillageFeatures()

        for slot_name, slot_values in FEATURE_SLOTS.items():
            for value in slot_values:
                if value in village_profile:
                    if slot_name == "sensitive_attr":
                        features.sensitive_attr.append(value)
                    else:
                        setattr(features, slot_name, value)

        return features

    def build_query(
        self,
        dimension_key: str,
        dimension_name: str,
        layer: int,
        village_features: VillageFeatures,
        layer2_summary: Optional[str] = None
    ) -> str:
        """构建结构化查询"""

        features_summary = self._format_features(village_features)

        if layer == 1:
            return self.LAYER1_TEMPLATE.format(
                features_summary=features_summary,
                dimension_name=dimension_name
            )
        elif layer == 3:
            return self.LAYER3_TEMPLATE.format(
                features_summary=features_summary,
                layer2_summary=layer2_summary or "待定",
                dimension_name=dimension_name
            )
        else:
            # Layer 2 不使用 RAG（rag_enabled=False）
            return ""

    def _format_features(self, features: VillageFeatures) -> str:
        """格式化特征槽为摘要字符串"""
        parts = []
        if features.geo_location:
            parts.append(f"地理区位-{features.geo_location}")
        if features.sensitive_attr:
            parts.append(f"敏感属性-{','.join(features.sensitive_attr)}")
        if features.population_feature:
            parts.append(f"人口特征-{features.population_feature}")
        if features.economic_type:
            parts.append(f"经济类型-{features.economic_type}")
        return ','.join(parts) if parts else "普通村庄"


# ==========================================
# 导出
# ==========================================

__all__ = [
    "FEATURE_SLOTS",
    "VillageFeatures",
    "RAGQueryBuilder",
    "get_dimension_name",  # Re-exported from dimension_metadata
]