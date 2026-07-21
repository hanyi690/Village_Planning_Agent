"""Deterministic section classifier — keyword-based, no LLM.

Replaces classify_sections LLM call for ~70% of sections.
Falls back to LLM only for low-confidence (score < 2) sections.

Token savings: 8K per call → 0 LLM for high-confidence, 2K-3K for fallbacks.
"""

from __future__ import annotations

from typing import Optional

from .markdown_parser import detect_table

# ── Keyword classification table ─────────────────────────────────────

SECTION_KEYWORDS: dict[str, set[str]] = {
    "preamble": {"前言", "概述", "背景", "依据", "总则", "规划范围", "规划期限", "编制依据", "指导思想"},
    "target": {"规划目标", "发展目标", "指标", "目标年", "规划人口", "建设用地规模", "耕地保有量",
              "基本农田", "人均", "目标表", "约束性指标", "预期性指标"},
    "regulation": {"管制规则", "建设管控", "禁止", "不得", "保护规则", "管控要求", "空间管制",
                   "用途管制", "分区管制", "准入", "退出"},
    "project_table": {"建设项目", "项目名称", "投资概算", "建设时序", "重点项目", "项目清单",
                      "实施项目", "近期建设", "远期建设", "工程", "投资"},
    "land_use_table": {"土地利用", "分类表", "地类表", "结构表", "用地结构", "地类统计",
                       "用地分类", "用途分区", "土地利用现状", "规划地类"},
    "indicator_table": {"规划指标", "指标表", "指标统计", "规划控制指标", "约束指标", "预期指标"},
    "heritage_table": {"历史文化", "文物保护", "历史建筑", "非遗", "传统村落", "古树名木", "古迹"},
    "facility_table": {"公共设施", "基础设施表", "配套", "公共服务", "设施配置", "服务半径",
                       "教育设施", "医疗设施", "文体设施", "社会福利", "商业服务"},
    "ecological_table": {"生态保护", "生态修复", "环境保护", "污染", "绿化", "生态用地",
                         "生态红线", "自然保护", "水源", "水土保持"},
    "spatial_layout": {"空间布局", "空间结构", "格局", "总体布局", "规划结构", "功能分区",
                       "用地布局", "带状", "组团", "一核", "两轴", "三区"},
    "protection": {"保护区域", "基本农田", "生态红线", "永久基本农田", "文化保护", "历史建筑",
                   "保护范围", "禁建区", "限建区", "适建区"},
    "infrastructure": {"基础设施", "道路", "供水", "排水", "电力", "通信", "燃气", "供热",
                       "环卫", "防灾", "消防", "交通", "管网"},
    "governance": {"实施", "保障", "监督", "管理", "监测", "评估", "考核", "措施", "组织",
                   "资金", "用地保障", "政策"},
}


def classify_section(title: str, content: str) -> tuple[str, int]:
    """Classify a section by keyword scoring.

    Returns (section_type, score) where:
      score >= 2  → high confidence, use directly
      score == 1  → medium, use with caution
      score == 0  → low confidence, route to LLM

    The scorer checks both title and first 500 chars of content for
    keyword hits. Each hit contributes +1 to the score.

    Args:
        title: Section heading text
        content: Section body text (first 500 chars used for scoring)

    Returns:
        (best_section_type, score) tuple
    """
    search_text = (title + " " + content[:500])
    scores: dict[str, int] = {}

    for stype, keywords in SECTION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in search_text)
        if score > 0:
            scores[stype] = score

    if not scores:
        return ("preamble", 0)

    best = max(scores, key=lambda k: scores[k])
    return (best, scores[best])


def needs_llm_fallback(section_type: str, score: int) -> bool:
    """Determine if section needs LLM fallback classification.

    Threshold: score < 2 means too few keyword matches, LLM should handle it.
    """
    return score < 2


def build_fallback_prompt(sections: list[dict]) -> str:
    """Build prompt for LLM fallback: only the low-confidence sections.

    This keeps the LLM input much smaller than sending the full document.
    """
    lines = ["请对以下段落的类型进行再确认。每个段落输出 section_type。\n"]
    for i, s in enumerate(sections):
        lines.append(f"## 段落{i + 1}\n标题: {s['title']}\n内容: {s['content'][:300]}\n")
    return "\n".join(lines)
