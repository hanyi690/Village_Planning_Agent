"""L3 报告 → session 功能区词汇表提取器（LLM 自由给色，确定性 fallback）。

v4 设计：功能区类别来自 DB L3 报告的【功能分区表】等章节（系统内闭环），
每轮随报告变化；提取结果注册为 session 级 Vocabulary（轮内闭集），
CustomZoningGenerator 消费后产出 L4 FunctionalZone。

LLM 边界：LLM 只产"类别定义"（名称/颜色自由给/地类线索/依据），
不产几何、不产 BSM。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.modules.schema.contracts.custom_zone_contracts import (
    TypingRule,
    Vocabulary,
    VocabularyCategory,
)
from app.modules.schema.encodings.dicts.vocabularies.loader import register_vocabulary
from app.utils.logger import get_logger

logger = get_logger(__name__)

_COLOR_POOL = [
    "#2d6a4f", "#9b51e0", "#c9d67a", "#4ea8de",
    "#f2994a", "#adb5bd", "#e85d75", "#f2c94c",
]

# 现状用地分类码（bundle landuse_current 的 dlbm 体系，非规划分类码）
_DLBM_HINTS: Dict[str, List[str]] = {
    "生态": ["1340", "1350"],
    "农田": ["1100"],
    "农业": ["1100", "1200", "1400"],
    "村庄": ["2121", "2122"],
    "建设": ["2121", "2122", "2124"],
    "林业": ["1340", "1350"],
    "旅游": ["1100", "1200", "1340", "3100"],
    "康养": ["1340", "1350", "3100"],
    "历史": ["2122", "2123"],
}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_PROTECTION_KEYWORDS = ("生态", "保护", "农田", "基本农田", "保育")


def _is_protection(name: str) -> bool:
    return any(kw in name for kw in _PROTECTION_KEYWORDS)


def _default_dlbm_for(name: str) -> List[str]:
    for kw, codes in _DLBM_HINTS.items():
        if kw in name:
            return codes
    return ["0101"]


def extract_vocabulary_deterministic(reports: Dict[str, str]) -> Vocabulary:
    """无 LLM 兜底：从报告分区表提取类别，语义推断颜色与地类线索。"""
    from app.modules.parsing.tables import _extract_zone_tables

    categories: List[VocabularyCategory] = []
    seen = set()
    for content in (reports or {}).values():
        zone_targets = list(_extract_zone_tables(content))
        try:
            from app.agent.gis.parse.agent import _extract_instruction_tables

            zone_targets.extend(
                (_extract_instruction_tables(content).get("zones") or [])
            )
        except Exception:
            pass
        for zt in zone_targets:
            name = zt.land_use
            if name in seen:
                continue
            seen.add(name)
            categories.append(
                VocabularyCategory(
                    code=f"FZ{len(categories) + 1:02d}",
                    name_zh=name,
                    color=_COLOR_POOL[len(categories) % len(_COLOR_POOL)],
                    typing_rules=[TypingRule(kind="dlbm_in", value=_default_dlbm_for(name))],
                    is_protection=_is_protection(name),
                )
            )
    return Vocabulary(name="l3_extracted", categories=categories)


_VOCAB_PROMPT = """你是村庄规划功能区词汇提取助手。从下列 L3 报告的功能分区内容中提取功能区类别定义。

报告内容：
{reports}

只输出 JSON（不要任何其他文字）：
{{"categories": [{{"name_zh": "林下开发区", "color": "#c9d67a", "dlbm_hints": ["1340", "1350"], "is_protection": false,
  "rules": [{{"kind": "dlbm_in", "value": ["1340", "1350"]}},
           {{"kind": "not_within_zone", "value": "in_ecological_redline"}},
           {{"kind": "road_distance_lt", "value": 500}}],
  "evidence": "报告原文依据句"}}]}}
要求：
- color 必须是合法的 hex 格式（#RRGGBB），由你自由选择
- dlbm_hints 是推测的**现状用地分类码**（1100 耕地、1200 园地、1340 商品林、1350 生态林、2121 宅基地、2124 经营性建设用地、3100 水域）
- is_protection: 生态/保护/农田类功能区为 true（与三线重合），建设/产业类为 false
- rules 是复合规则表达式（可选，缺省时用 dlbm_hints），谓词白名单：
    dlbm_in[码数组] / within_zone[区域] / not_within_zone[区域] /
    slope_lt[度] / road_distance_lt[米] / near_poi[名称] /
    and[子规则数组] / any[子规则数组] / not[子规则数组]
- 地块上下文因子（生成 slope_lt / road_distance_lt 时依赖）：
    坡度 slope_deg（度，0-90，由 DEM 逐地块质心计算）/ 道路距离 road_distance_m（质心到最近现状道路）/ 所在功能区 zone_membership / 附近 POI
- 生态/林地类功能区建议用 slope_lt（如 25 度）表达；面积目标由 L3 分区表给出，
  rules 只需表达"哪些地块算"，不必精确卡面积
- 若没有可提取的功能区，输出 {{"categories": []}}
"""


async def _extract_vocabulary_llm(llm: Any, reports: Dict[str, str]) -> Vocabulary:
    reports_text = "\n\n".join(f"[{k}]\n{v[:3000]}" for k, v in (reports or {}).items())
    prompt = _VOCAB_PROMPT.format(reports=reports_text[:9000])

    resp = await llm.ainvoke(prompt)
    content = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("[VocabExtractor] LLM output not JSON: %s", content[:200])
        raise ValueError("LLM output not JSON")
    data = json.loads(m.group(0))

    categories: List[VocabularyCategory] = []
    for item in data.get("categories") or []:
        name = str(item.get("name_zh", "")).strip()
        color = str(item.get("color", "")).strip()
        if not name:
            continue
        if not _HEX_RE.match(color):
            color = _COLOR_POOL[len(categories) % len(_COLOR_POOL)]
        hints = [str(c) for c in (item.get("dlbm_hints") or [])][:6]
        rules = _parse_rules(item.get("rules"), hints)
        categories.append(
            VocabularyCategory(
                code=f"FZ{len(categories) + 1:02d}",
                name_zh=name,
                color=color,
                typing_rules=rules or [TypingRule(kind="dlbm_in", value=hints or _default_dlbm_for(name))],
                is_protection=bool(item.get("is_protection")) or _is_protection(name),
            )
        )
    return Vocabulary(name="l3_extracted", categories=categories)


_ALLOWED_KINDS = {
    "dlbm_in", "within_zone", "not_within_zone", "slope_lt",
    "road_distance_lt", "near_poi", "and", "any", "not",
}


def _parse_rules(raw: Any, fallback_hints: List[str]) -> List[TypingRule]:
    """LLM 输出 rules → TypingRule（有界谓词白名单，非法谓词丢弃）。"""
    if not isinstance(raw, list):
        return []
    rules: List[TypingRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        if kind not in _ALLOWED_KINDS:
            continue
        if kind in ("and", "any", "not"):
            children = _parse_rules(item.get("children") or item.get("rules"), [])
            if children:
                rules.append(TypingRule(kind=kind, children=children))
        else:
            value = item.get("value")
            if value is not None:
                rules.append(TypingRule(kind=kind, value=value))
    return rules


async def extract_vocabulary_from_reports(
    reports: Dict[str, str],
    llm: Any = None,
) -> Vocabulary:
    """Extract a session vocabulary from L3 reports.

    Flash LLM when available (GIS_EXPLORE_LLM_ENABLED); deterministic table
    extraction as fallback.  Caller registers the result per session.
    """
    if llm is None:
        from app.core.settings import GIS_EXPLORE_LLM_ENABLED

        if GIS_EXPLORE_LLM_ENABLED:
            from app.core.llm import create_llm
            from app.core.settings import (
                GIS_EXPLORE_MAX_TOKENS,
                GIS_EXPLORE_MODEL,
                GIS_EXPLORE_TEMPERATURE,
            )

            llm = create_llm(
                model=GIS_EXPLORE_MODEL,
                temperature=GIS_EXPLORE_TEMPERATURE,
                max_tokens=GIS_EXPLORE_MAX_TOKENS,
                streaming=False,
            )

    if llm is not None:
        try:
            llm_vocab = await _extract_vocabulary_llm(llm, reports)
            # v5: 表格闭集 — 分区类别以 L3 报告分区表为唯一来源（防 LLM 编造），
            # LLM 只增强已存在类别的 color/dlbm_hints/is_protection
            det = extract_vocabulary_deterministic(reports)
            if det.categories:
                by_name = {c.name_zh: c for c in det.categories}
                for c in llm_vocab.categories:
                    if c.name_zh in by_name:
                        by_name[c.name_zh].color = c.color
                        by_name[c.name_zh].typing_rules = c.typing_rules or by_name[c.name_zh].typing_rules
                        by_name[c.name_zh].is_protection = c.is_protection or by_name[c.name_zh].is_protection
                return Vocabulary(name="l3_extracted", categories=list(by_name.values()))
            logger.info("[VocabExtractor] no table categories, falling back to deterministic")
        except Exception as e:
            logger.warning("[VocabExtractor] LLM extraction failed: %s", e)
    return extract_vocabulary_deterministic(reports)


def register_session_vocabulary(session_id: str, vocab: Vocabulary) -> str:
    """Register the vocabulary under a session-scoped name and return it."""
    name = f"{session_id}_vocab"
    register_vocabulary(name, vocab)
    return name


__all__ = [
    "extract_vocabulary_from_reports",
    "extract_vocabulary_deterministic",
    "register_session_vocabulary",
]
