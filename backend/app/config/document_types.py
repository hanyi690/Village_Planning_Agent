"""
统一维度定义和文档类型标注规则
"""

from typing import Dict, List, Set
import re


DIMENSIONS: Dict[str, Dict] = {
    "land_use": {
        "keywords": ["用地", "土地", "三区三线", "建设用地", "农用地", "宅基地"],
        "definition": "土地利用、建设用地、宅基地、三区三线相关",
    },
    "infrastructure": {
        "keywords": ["给排水", "供水", "排水", "电力", "通信", "环卫"],
        "definition": "给排水、电力、通信、环卫设施相关",
    },
    "ecological_green": {
        "keywords": ["生态", "绿地", "景观", "绿化", "公园"],
        "definition": "生态保护、绿地景观、绿化规划相关",
    },
    "historical_culture": {
        "keywords": ["文物", "历史", "文化", "保护", "古建筑"],
        "definition": "文物古迹、历史文化、传统村落相关",
    },
    "traffic": {
        "keywords": ["道路", "交通", "路网", "停车"],
        "definition": "道路交通、路网规划、交通设施相关",
    },
    "location": {
        "keywords": ["区位", "位置", "边界", "行政区划"],
        "definition": "区位条件、地理位置、行政区划相关",
    },
    "socio_economic": {
        "keywords": ["经济", "产业", "收入", "人口", "GDP"],
        "definition": "社会经济、产业发展、人口收入相关",
    },
    "villager_wishes": {
        "keywords": ["意愿", "诉求", "需求", "建议"],
        "definition": "村民意愿、诉求需求、民意调查相关",
    },
    "superior_planning": {
        "keywords": ["上位规划", "政策", "法规", "纲要"],
        "definition": "上位规划、政策法规、规划纲要相关",
    },
    "natural_environment": {
        "keywords": ["自然", "环境", "气候", "地形", "地貌"],
        "definition": "自然环境、气候地形、地质水文相关",
    },
    "public_services": {
        "keywords": ["公共服务", "教育", "医疗", "养老"],
        "definition": "公共服务设施、教育医疗、文化体育相关",
    },
    "architecture": {
        "keywords": ["建筑", "房屋", "住宅", "风貌"],
        "definition": "建筑风貌、房屋质量、民居改造相关",
    },
    "disaster_prevention": {
        "keywords": ["灾害", "防灾", "消防", "防洪"],
        "definition": "防灾减灾、消防防洪、应急预案相关",
    },
    "industry_development": {
        "keywords": ["产业", "发展", "特色", "农业", "旅游"],
        "definition": "产业发展、特色产业、农业旅游相关",
    },
    "governance": {
        "keywords": ["治理", "组织", "党建", "村规民约"],
        "definition": "乡村治理、党建组织、村规民约相关",
    },
}

DIMENSION_KEYS: List[str] = list(DIMENSIONS.keys())


def get_dimension_keywords() -> Dict[str, List[str]]:
    return {dim: data["keywords"] for dim, data in DIMENSIONS.items()}


def get_dimension_definitions() -> Dict[str, str]:
    return {dim: data["definition"] for dim, data in DIMENSIONS.items()}


def get_dimension_by_keyword(keyword: str) -> str:
    for dim, data in DIMENSIONS.items():
        if keyword in data["keywords"]:
            return dim
    return "general"


TERRAIN_KEYWORDS: Dict[str, List[str]] = {
    "mountain": ["山区", "山地", "丘陵", "坡"],
    "plain": ["平原", "盆地", "平坦"],
    "hill": ["丘陵", "岗地", "低山"],
    "coastal": ["沿海", "滨海", "海岛"],
    "riverside": ["沿江", "滨河", "水乡"],
}


DOCUMENT_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "policy": ["政策", "意见", "办法", "规定", "条例"],
    "standard": ["标准", "规范", "规程", "技术", "GB"],
    "case": ["案例", "示范", "典型", "经验"],
    "guide": ["指南", "手册", "教程", "指导"],
    "report": ["报告", "调研", "分析", "研究"],
}


class DimensionTagger:
    """维度标注器"""

    def __init__(self):
        self.dimension_keywords: Dict[str, Set[str]] = {}
        for dim, keywords in get_dimension_keywords().items():
            self.dimension_keywords[dim] = set(keywords)

    def detect_dimensions(self, content: str, top_k: int = 3) -> List[str]:
        if not content:
            return []
        dimension_scores: Dict[str, int] = {}
        for dim, keywords in self.dimension_keywords.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                dimension_scores[dim] = score
        sorted_dims = sorted(dimension_scores.items(), key=lambda x: x[1], reverse=True)
        return [dim for dim, score in sorted_dims[:top_k] if score > 0]

    def detect_dimensions_for_filename(self, filename: str) -> List[str]:
        if not filename:
            return []
        detected = []
        for dim, keywords in self.dimension_keywords.items():
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
        if not content:
            return "all"
        terrain_scores: Dict[str, int] = {}
        for terrain, keywords in self.terrain_keywords.items():
            score = sum(1 for kw in keywords if kw in content)
            if score > 0:
                terrain_scores[terrain] = score
        if not terrain_scores:
            return "all"
        return max(terrain_scores.items(), key=lambda x: x[1])[0]


class DocumentTypeTagger:
    """文档类型标注器"""

    def __init__(self):
        self.doc_type_keywords: Dict[str, Set[str]] = {}
        for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
            self.doc_type_keywords[doc_type] = set(keywords)

    def detect_doc_type(self, content: str, filename: str = "") -> str:
        if filename:
            for doc_type, keywords in self.doc_type_keywords.items():
                if any(kw in filename for kw in keywords):
                    return doc_type
        if content:
            type_scores: Dict[str, int] = {}
            for doc_type, keywords in self.doc_type_keywords.items():
                score = sum(1 for kw in keywords if kw in content)
                if score > 0:
                    type_scores[doc_type] = score
            if type_scores:
                return max(type_scores.items(), key=lambda x: x[1])[0]
        return "general"


REGION_PATTERNS: Dict[str, List[str]] = {
    "province": ["省", "自治区", "直辖市"],
    "city": ["市", "自治州", "地区"],
    "county": ["县", "县级市", "区", "旗"],
    "town": ["镇", "乡", "街道"],
    "village": ["村", "社区"],
}


def extract_regions_from_text(content: str) -> List[str]:
    regions = []
    patterns = [
        r'([\u4e00-\u9fa5]+省)',
        r'([\u4e00-\u9fa5]+市)',
        r'([\u4e00-\u9fa5]+县)',
        r'([\u4e00-\u9fa5]+镇)',
        r'([\u4e00-\u9fa5]+村)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, content)
        regions.extend(matches)
    return list(set(regions))


__all__ = [
    "DIMENSIONS",
    "DIMENSION_KEYS",
    "TERRAIN_KEYWORDS",
    "DOCUMENT_TYPE_KEYWORDS",
    "get_dimension_keywords",
    "get_dimension_definitions",
    "get_dimension_by_keyword",
    "extract_regions_from_text",
    "DimensionTagger",
    "TerrainTagger",
    "DocumentTypeTagger",
]