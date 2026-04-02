"""
标注规则配置

定义 24 个分析维度的关键词映射表、地形特征词库、地区识别规则。
"""
from typing import List, Set, Dict
from pathlib import Path


# ==================== 24 个分析维度关键词映射 ====================

DIMENSION_KEYWORDS: Dict[str, List[str]] = {
    # === Layer 1: 基础现状维度 ===
    "land_use": [
        "用地", "土地", "三区三线", "建设用地", "农用地", "未利用地",
        "基本农田", "耕地", "宅基地", "集体建设用地", "土地整治",
        "用地布局", "土地利用", "土地性质", "用地分类", "GB/T 32000",
    ],
    "infrastructure": [
        "给排水", "供水", "排水", "污水处理", "电力", "通信", "环卫",
        "垃圾收集", "厕所", "管线", "基础设施", "市政设施",
        "供电", "电讯", "广播电视", "燃气", "供热",
    ],
    "ecological_green": [
        "生态", "绿地", "景观", "绿化", "防护绿地", "公园", "广场",
        "生态保护", "水源地", "生态红线", "环境优美", "绿水青山",
        "植被", "林地", "草地", "湿地", "生态敏感区",
    ],
    "historical_culture": [
        "文物", "历史", "文化", "保护", "古建筑", "传统", "非遗",
        "历史文化名村", "传统村落", "文物保护单元", "历史建筑",
        "民俗", "民族文化", "文化遗产", "古迹", "遗址",
    ],
    "traffic": [
        "道路", "交通", "红线", "车行", "步行", "停车", "公交",
        "路网", "干路", "支路", "巷道", "对外交通", "交通组织",
        "道路宽度", "路面硬化", "路灯", "交通设施",
    ],

    # === Layer 2: 综合分析维度 ===
    "location": [
        "区位", "位置", "地理", "坐标", "边界", "面积", "四至",
        "行政区划", "管辖", "辖区", "地理中心", "经济圈",
        "交通区位", "经济区位", "战略位置",
    ],
    "socio_economic": [
        "经济", "产业", "收入", "人口", "GDP", "财政", "集体",
        "村民", "农户", "贫困户", "脱贫", "乡村振兴",
        "农业", "工业", "服务业", "旅游", "特色产", "合作社",
        "人均可支配收入", "集体经济收入",
    ],
    "villager_wishes": [
        "意愿", "诉求", "需求", "希望", "建议", "意见", "反馈",
        "村民代表", "访谈", "问卷", "调查", "民意", "期盼",
        "改善", "要求", "愿望", "满意度",
    ],
    "superior_planning": [
        "上位规划", "政策", "法规", "规划", "纲要", "方案",
        "十四五", "乡村振兴", "战略规划", "总体规划", "专项规划",
        "指导意见", "管理办法", "实施细则", "国家标准", "行业标准",
    ],
    "natural_environment": [
        "自然", "环境", "气候", "地形", "地貌", "地质", "气象",
        "气温", "降雨", "风向", "海拔", "坡度", "坡向",
        "自然灾害", "地质", "水文", "土壤", "植被",
    ],
    "public_services": [
        "公共服务", "设施", "教育", "医疗", "卫生", "文化", "体育",
        "养老", "幼托", "便民", "服务中心", "活动", "广场",
        "卫生室", "幼儿园", "小学", "敬老院", "文化活动",
    ],
    "architecture": [
        "建筑", "房屋", "住宅", "质量", "风貌", "层高", "结构",
        "危房", "改造", "外立面", "建筑风格", "民居", "农房",
        "建筑面积", "建筑密度", "建筑风貌", "闲置", "空置",
    ],

    # === Layer 3: 专项分析维度 ===
    "disaster_prevention": [
        "灾害", "防灾", "消防", "防洪", "排涝", "抗震", "避险",
        "应急预案", "疏散", "避难", "消防栓", "灭火器",
        "山洪", "滑坡", "泥石流", "内涝", "干旱", "台风",
    ],
    "industry_development": [
        "产业", "发展", "特色", "农业", "工业", "旅游", "服务",
        "产业园", "基地", "合作社", "家庭农场", "龙头企业",
        "品牌", "商标", "认证", "有机", "绿色", "地理标志",
    ],
    "governance": [
        "治理", "组织", "党建", "支部", "委员会", "理事会",
        "自治", "法治", "德治", "村规民约", "管理制度",
        "党员", "干部", "村民自治", "民主", "公开",
    ],
}

# 地形类型关键词映射
TERRAIN_KEYWORDS: Dict[str, List[str]] = {
    "mountain": [
        "山区", "山地", "丘陵", "坡", "高", "海拔", "山", "峰",
        "谷", "岭", "崎岖", "陡", "峻", "高山", "深山",
    ],
    "plain": [
        "平原", "盆地", "平坦", "平地", "沃野", "一马平川",
        "低平", "开阔", "平坝", "坝子", "冲积",
    ],
    "hill": [
        "丘陵", "岗地", "低山", "缓坡", "台地", "垅岗",
        "起伏", "岗丘", "红壤", "梯田",
    ],
    "coastal": [
        "沿海", "滨海", "海岛", "海岸", "滩涂", "海湾",
        "渔港", "海岸带", "近海", " offshore",
    ],
    "riverside": [
        "沿江", "滨河", "河畔", "水乡", "沿河", "临河",
        "流域", "水岸", "河网", "水系",
    ],
}

# 文档类型识别关键词
DOCUMENT_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "policy": [
        "政策", "意见", "指导", "办法", "规定", "条例", "法规",
        "通知", "决定", "方案", "纲要", "规划", "计划",
    ],
    "standard": [
        "标准", "规范", "规程", "技术", "指标", "要求", "GB", "DB",
        "行业标准", "国家标准", "地方标准", "技术导则",
    ],
    "case": [
        "案例", "示范", "典型", "经验", "模式", "实践", "实例",
        "成功", "借鉴", "参考", "村", "镇",
    ],
    "guide": [
        "指南", "手册", "教程", "指导", "参考", "解读", "说明",
        "培训", "知识", "介绍", "概述",
    ],
    "report": [
        "报告", "调研", "调查", "分析", "研究", "评估", "评价",
        "可研", "方案", "汇报", "总结", "规划",
    ],
}


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
