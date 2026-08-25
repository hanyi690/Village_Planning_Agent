"""L3 报告 → session 功能区词汇表提取器。

Vocabulary extraction follows the current materialization boundary in docs/design/03_PLANNING_EXECUTION.md.

v4 设计：功能区类别来自 DB L3 报告的【功能分区表】等章节（系统内闭环），
每轮随报告变化；提取结果注册为 session 级 Vocabulary（轮内闭集），
CustomZoningGenerator 消费后产出 L4 FunctionalZone。

LLM 边界：LLM 只产"类别定义"（名称/颜色自由给/地类线索/依据），
不产几何、不产 BSM。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.contracts.domain.custom_zone_contracts import (
    TypingRule,
    Vocabulary,
    VocabularyCategory,
)
from app.data.encodings.dicts.vocabularies.loader import register_vocabulary
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_COLOR_POOL = [
    "#2d6a4f", "#9b51e0", "#c9d67a", "#4ea8de",
    "#f2994a", "#adb5bd", "#e85d75", "#f2c94c",
]

_PROTECTION_KEYWORDS = ("生态", "保护", "农田", "基本农田", "保育")


class _VocabularyRuleOutput(BaseModel):
    kind: str
    value: Any = None
    children: list["_VocabularyRuleOutput"] = Field(default_factory=list)


class _VocabularyCategoryOutput(BaseModel):
    name_zh: str
    color: str = ""
    dlbm_hints: list[str] = Field(default_factory=list)
    is_protection: bool = False
    rules: list[_VocabularyRuleOutput] = Field(default_factory=list)


class _VocabularyOutput(BaseModel):
    categories: list[_VocabularyCategoryOutput] = Field(default_factory=list)


def _is_hex_color(value: str) -> bool:
    if len(value) != 7 or value[0] != "#":
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[1:])


def _is_protection(name: str) -> bool:
    return any(kw in name for kw in _PROTECTION_KEYWORDS)


def extract_vocabulary_deterministic(reports: Dict[str, str]) -> Vocabulary:
    """无 LLM 兜底：从报告分区表提取类别，语义推断颜色与地类线索。"""
    from app.data.ingestion.tables import _extract_zone_tables

    categories: List[VocabularyCategory] = []
    seen = set()
    for content in (reports or {}).values():
        zone_targets = list(_extract_zone_tables(content))
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
                    typing_rules=[],
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
           {{"kind": "road_distance_lt", "value": 500}}]
  }}]}}
要求：
- category 对象只能包含 name_zh、color、dlbm_hints、is_protection、rules；不要输出 evidence 或其他字段
- rule 对象只能包含 kind、value、children；kind 必须来自下列谓词白名单
- color 必须是合法的 hex 格式（#RRGGBB），由你自由选择
- dlbm_hints 仅可作为 rules 中显式 dlbm_in 的候选值；它不是规划分类，也不能单独产生分类结果
- is_protection: 生态/保护/农田类功能区为 true（与三线重合），建设/产业类为 false
- rules 是复合规则表达式（可选；缺省时不产生地类规则），谓词白名单：
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

    structured = llm.with_structured_output(_VocabularyOutput)
    invoke = getattr(structured, "ainvoke", None)
    if callable(invoke):
        response = await invoke(prompt)
    else:
        response = await asyncio.to_thread(structured.invoke, prompt)
    data = response if isinstance(response, _VocabularyOutput) else _VocabularyOutput.model_validate(response)

    categories: List[VocabularyCategory] = []
    for item in data.categories:
        name = str(item.name_zh or "").strip()
        color = str(item.color or "").strip()
        if not name:
            continue
        if not _is_hex_color(color):
            color = _COLOR_POOL[len(categories) % len(_COLOR_POOL)]
        rules = _parse_rules(item.rules)
        categories.append(
            VocabularyCategory(
                code=f"FZ{len(categories) + 1:02d}",
                name_zh=name,
                color=color,
                typing_rules=rules,
                is_protection=bool(item.is_protection) or _is_protection(name),
            )
        )
    return Vocabulary(name="l3_extracted", categories=categories)


_ALLOWED_KINDS = {
    "dlbm_in", "within_zone", "not_within_zone", "slope_lt",
    "road_distance_lt", "near_poi", "and", "any", "not",
}


def _parse_rules(raw: list[_VocabularyRuleOutput]) -> List[TypingRule]:
    """Convert the typed LLM rule tree through the predicate whitelist."""
    if not isinstance(raw, list):
        return []
    rules: List[TypingRule] = []
    for item in raw:
        kind = str(item.kind or "")
        if kind not in _ALLOWED_KINDS:
            continue
        if kind in ("and", "any", "not"):
            children = _parse_rules(item.children)
            if children:
                rules.append(TypingRule(kind=kind, children=children))
        else:
            value = item.value
            if value is not None:
                rules.append(TypingRule(kind=kind, value=value))
    return rules


async def extract_vocabulary_from_reports(
    reports: Dict[str, str],
    llm: Any = None,
) -> Vocabulary:
    """Extract a session vocabulary from L3 reports.

    Use typed LLM output when the LLM path is enabled or injected.  The
    deterministic table compiler is available only when LLM extraction is
    explicitly disabled; a provider failure is raised to the caller.
    """
    if llm is None:
        from app.core.settings import GIS_EXPLORE_LLM_ENABLED

        if not GIS_EXPLORE_LLM_ENABLED:
            return extract_vocabulary_deterministic(reports)
        from app.infrastructure.llm.factory import create_llm
        from app.core.settings import (
            GIS_EXPLORE_MAX_TOKENS,
            GIS_EXPLORE_TEMPERATURE,
        )

        llm = create_llm(
            model=None,
            temperature=GIS_EXPLORE_TEMPERATURE,
            max_tokens=GIS_EXPLORE_MAX_TOKENS,
            streaming=False,
        )

    try:
        return await _extract_vocabulary_llm(llm, reports)
    except Exception as exc:
        logger.error("[VocabExtractor] typed LLM extraction failed: %s", type(exc).__name__)
        raise RuntimeError("typed_vocabulary_extraction_failed") from exc


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
