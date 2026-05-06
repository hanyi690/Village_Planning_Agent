"""
标注规则配置

定义 24 个分析维度的关键词映射表、地形特征词库、地区识别规则。
使用统一定义文件（definitions.py）作为数据源。
"""
from typing import List, Set, Dict
from pathlib import Path

# 导入统一定义
from .definitions import (
    DIMENSIONS,
    get_dimension_keywords,
    TERRAIN_KEYWORDS,
    DOCUMENT_TYPE_KEYWORDS,
)


# ==================== 从统一定义导出（向后兼容） ====================

DIMENSION_KEYWORDS: Dict[str, List[str]] = get_dimension_keywords()


class DimensionTagger:
    """维度标注器"""

    def __init__(self):
        # 预编译关键词集合，提高匹配效率
        self.dimension_keywords: Dict[str, Set[str]] = {}
        for dim, keywords in DIMENSION_KEYWORDS.items():
            self.dimension_keywords[dim] = set(keywords)

    def detect_dimensions(self, content: str, top_k: int = 3) -> List[str]:
        """
        基于内容检测适用的维度

        Args:
            content: 文档内容
            top_k: 返回最相关的维度数量

        Returns:
            维度标识列表
        """
        if not content:
            return []

        # 统计每个维度的匹配词数量
        dimension_scores: Dict[str, int] = {}

        for dim, keywords in self.dimension_keywords.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                dimension_scores[dim] = score

        # 按得分排序，返回 top_k
        sorted_dims = sorted(
            dimension_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # 返回有匹配的维度
        return [dim for dim, score in sorted_dims[:top_k] if score > 0]

    def detect_dimensions_for_filename(self, filename: str) -> List[str]:
        """基于文件名检测维度"""
        if not filename:
            return []

        detected = []
        for dim, keywords in self.dimension_keywords.items():
            # 检查文件名是否包含维度关键词
            if any(kw in filename for kw in keywords):
                detected.append(dim)

        return detected if detected else ["general"]


class TerrainTagger:
    """地形标注器"""

    def __init__(self):
        self.terrain_keywords: Dict[str, Set[str]] = {}
        for terrain, keywords in TERRAIN_KEYWORDS.items():
            self.terrain_keywords[terrain] = set(keywords)

    def detect_terrain(self, content: str) -> str:
        """
        基于内容检测地形类型

        Args:
            content: 文档内容

        Returns:
            地形类型标识，默认返回 "all"
        """
        if not content:
            return "all"

        # 统计每种地形的匹配得分
        terrain_scores: Dict[str, int] = {}

        for terrain, keywords in self.terrain_keywords.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                terrain_scores[terrain] = score

        if not terrain_scores:
            return "all"

        # 返回得分最高的地形
        return max(terrain_scores.items(), key=lambda x: x[1])[0]

    def detect_terrain_from_filename(self, filename: str) -> str:
        """基于文件名检测地形"""
        if not filename:
            return "all"

        for terrain, keywords in self.terrain_keywords.items():
            if any(kw in filename for kw in keywords):
                return terrain

        return "all"


class DocumentTypeTagger:
    """文档类型标注器"""

    def __init__(self):
        self.doc_type_keywords: Dict[str, Set[str]] = {}
        for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
            self.doc_type_keywords[doc_type] = set(keywords)

    def detect_doc_type(self, content: str, filename: str = "") -> str:
        """
        基于内容和文件名检测文档类型

        Args:
            content: 文档内容
            filename: 文件名（可选）

        Returns:
            文档类型标识，默认返回 "general"
        """
        # 先从文件名检测
        if filename:
            for doc_type, keywords in self.doc_type_keywords.items():
                if any(kw in filename for kw in keywords):
                    return doc_type

        # 再从内容检测
        if content:
            type_scores: Dict[str, int] = {}

            for doc_type, keywords in self.doc_type_keywords.items():
                score = sum(1 for kw in keywords if kw in content)
                if score > 0:
                    type_scores[doc_type] = score

            if type_scores:
                return max(type_scores.items(), key=lambda x: x[1])[0]

        return "general"


# ==================== 地区识别规则 ====================

REGION_PATTERNS: Dict[str, List[str]] = {
    "province": [
        "省", "自治区", "直辖市",
    ],
    "city": [
        "市", "自治州", "地区",
    ],
    "county": [
        "县", "县级市", "区", "旗",
    ],
    "town": [
        "镇", "乡", "街道",
    ],
    "village": [
        "村", "社区",
    ],
}


def extract_regions_from_text(content: str) -> List[str]:
    """
    从文本中提取地区信息

    Args:
        content: 文档内容

    Returns:
        地区名称列表
    """
    import re

    regions = []

    # 匹配常见的行政区划模式
    patterns = [
        r'([\u4e00-\u9fa5]+省)',
        r'([\u4e00-\u9fa5]+自治区)',
        r'([\u4e00-\u9fa5]+市)',
        r'([\u4e00-\u9fa5]+县)',
        r'([\u4e00-\u9fa5]+区)',
        r'([\u4e00-\u9fa5]+镇)',
        r'([\u4e00-\u9fa5]+乡)',
        r'([\u4e00-\u9fa5]+村)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, content)
        regions.extend(matches)

    # 去重
    return list(set(regions))
