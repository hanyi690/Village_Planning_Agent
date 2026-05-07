"""
报告格式规范模块

定义法规式文档格式规范，用于村庄规划报告生成。

版本: 2026-05-07
作者: Village Planning Agent Team
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


# ============================================
# 章节编号规范
# ============================================

CHAPTER_NUMBERING = {
    "章": {
        "pattern": "第一章、第二章、第三章",
        "regex": r"^第[一二三四五六七八九十]+章\s+.+$",
        "example": "第一章 村庄现状",
    },
    "条": {
        "pattern": "第一条、第二条、第三条",
        "regex": r"^第[一二三四五六七八九十百]+条\s+.+$",
        "example": "第一条 区位与对外交通",
    },
    "分项": {
        "pattern": "（一）、（二）、（三）",
        "regex": r"（[一二三四五六七八九十]+）",
        "example": "（一）地理区位层级",
    },
    "子项": {
        "pattern": "（1）、（2）、（3）",
        "regex": r"（\d+）",
        "example": "（1）梅州市在广东省的位置",
    },
}


# ============================================
# 表格编号规范
# ============================================

TABLE_FORMAT = {
    "编号模式": {
        "pattern": "表X-X",
        "regex": r"表[ ]*\d+-\d+",
        "examples": ["表1-1", "表2-1", "表3-1"],
    },
    "标题位置": "表格上方",
    "单位行": "单独标注（如：单位：公顷）",
    "表头要求": "必须包含表头行（| 列名 | 列名 |）",
}


# ============================================
# 缺失数据处理规范
# ============================================

MISSING_DATA_ALTERNATIVES = [
    "根据现有数据推断，...",
    "建议补充调查，以完善分析。",
    "参考同类村庄经验，...",
    "待核实具体数据。",
    "需进一步调研确认。",
]

# 禁止使用的重复表述
FORBIDDEN_MISSING_PHRASES = [
    "数据中未提供此项信息",
    "数据中未提供",
    "未提供此项",
    "暂无数据",
]

# 各层级缺失表述次数限制
MISSING_PHRASE_LIMITS = {
    1: 5,  # Layer 1 现状报告
    2: 2,  # Layer 2 规划思路
    3: 3,  # Layer 3 规划细化
}


# ============================================
# 策略格式规范
# ============================================

STRATEGY_FORMAT = {
    "分隔符": {
        "required": "——",  # 全角破折号
        "forbidden": "-",  # 半横线
    },
    "结构": {
        "pattern": "[关键词]——[策略名称]（[具体措施]）",
        "example": "生态优先——生态保护网格化（针对现状35处滑坡隐患点问题，...）",
    },
    "编号": {
        "pattern": "（一）、（二）、（三）",
        "example": "（一）生态保护策略",
    },
}


# ============================================
# 各层级格式配置
# ============================================

@dataclass
class LayerFormatConfig:
    """层级格式配置"""
    layer: int
    name: str
    chapter_title: str
    chapter_regex: str
    item_regex: str
    subitem_regex: str
    table_regex: Optional[str] = None
    table_required: bool = False
    strategy_required: bool = False
    missing_phrase_limit: int = 5

    def get_validation_rules(self) -> Dict[str, Dict]:
        """获取验证规则"""
        rules = {
            "title": {
                "pattern": self.chapter_regex,
                "required": True,
            },
            "item_numbers": {
                "pattern": self.item_regex,
                "min_count": 1,
            },
            "subitem_numbers": {
                "pattern": self.subitem_regex,
            },
            "missing_phrases": {
                "limit": self.missing_phrase_limit,
                "forbidden": FORBIDDEN_MISSING_PHRASES,
                "alternatives": MISSING_DATA_ALTERNATIVES,
            },
        }

        if self.table_regex:
            rules["table_numbers"] = {
                "pattern": self.table_regex,
                "required": self.table_required,
            }

        if self.strategy_required:
            rules["strategy_format"] = {
                "separator": STRATEGY_FORMAT["分隔符"]["required"],
                "pattern": STRATEGY_FORMAT["结构"]["pattern"],
            }

        return rules


# 各层级配置实例
LAYER_FORMATS = {
    1: LayerFormatConfig(
        layer=1,
        name="Layer 1 现状报告",
        chapter_title="第一章 {村庄名} 村庄现状",
        chapter_regex=r"第一章\s+.+\s*村庄现状",
        item_regex=r"第[一二三四五六七八九十百]+条",
        subitem_regex=r"（[一二三四五六七八九十]+）|（\d+）",
        table_regex=r"表[ ]*1-\d+",
        table_required=True,
        missing_phrase_limit=5,
    ),
    2: LayerFormatConfig(
        layer=2,
        name="Layer 2 规划思路",
        chapter_title="第二章 {村庄名} 规划思路",
        chapter_regex=r"第二章\s+.+\s*规划思路",
        item_regex=r"第[一二三四五六七八九十百]+条",
        subitem_regex=r"（[一二三四五六七八九十]+）",
        table_regex=r"表[ ]*2-\d+",
        table_required=True,
        strategy_required=True,
        missing_phrase_limit=2,
    ),
    3: LayerFormatConfig(
        layer=3,
        name="Layer 3 规划细化",
        chapter_title="第三章 {村庄名} 规划细化",
        chapter_regex=r"第三章\s+.+\s*规划细化",
        item_regex=r"第[一二三四五六七八九十百]+条",
        subitem_regex=r"（[一二三四五六七八九十]+）",
        table_regex=r"表[ ]*3-\d+",
        table_required=True,
        missing_phrase_limit=3,
    ),
}


# ============================================
# 辅助函数
# ============================================

def get_layer_config(layer: int) -> LayerFormatConfig:
    """获取层级配置"""
    return LAYER_FORMATS.get(layer)


def get_chapter_title(layer: int, village_name: str) -> str:
    """生成章节标题"""
    config = get_layer_config(layer)
    if config:
        return config.chapter_title.format(village_name=village_name)
    return ""


def get_table_title(layer: int, table_num: int, table_name: str) -> str:
    """生成表格标题"""
    return f"表{layer}-{table_num} {table_name}"


def validate_separator(text: str) -> bool:
    """验证策略分隔符是否正确"""
    # 检查是否包含全角破折号
    has_full_dash = "——" in text
    # 检查是否错误使用半横线
    has_half_dash = "-" in text and "——" not in text
    return has_full_dash and not has_half_dash


def find_missing_phrases(text: str) -> List[Dict[str, str]]:
    """
    查找禁止的缺失表述并返回建议替代表述。

    Returns:
        List of dicts with keys: 'found', 'position', 'alternatives'
    """
    findings = []
    for forbidden in FORBIDDEN_MISSING_PHRASES:
        start = 0
        while True:
            pos = text.find(forbidden, start)
            if pos == -1:
                break
            findings.append({
                "found": forbidden,
                "position": pos,
                "alternatives": MISSING_DATA_ALTERNATIVES,
            })
            start = pos + len(forbidden)
    return findings


def validate_missing_phrase_quality(text: str) -> Dict[str, Any]:
    """
    验证缺失表述质量（仅检查，不替换）。

    Returns:
        Dict with keys: 'has_issues', 'count', 'details', 'suggestions'
    """
    findings = find_missing_phrases(text)
    return {
        "has_issues": len(findings) > 0,
        "count": len(findings),
        "details": findings,
        "suggestions": MISSING_DATA_ALTERNATIVES,
    }


# ============================================
# 导出
# ============================================

__all__ = [
    "CHAPTER_NUMBERING",
    "TABLE_FORMAT",
    "MISSING_DATA_ALTERNATIVES",
    "FORBIDDEN_MISSING_PHRASES",
    "MISSING_PHRASE_LIMITS",
    "STRATEGY_FORMAT",
    "LAYER_FORMATS",
    "LayerFormatConfig",
    "get_layer_config",
    "get_chapter_title",
    "get_table_title",
    "validate_separator",
    "find_missing_phrases",
    "validate_missing_phrase_quality",
]