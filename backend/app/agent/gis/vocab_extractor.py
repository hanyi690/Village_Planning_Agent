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

_DLBM_HINTS: Dict[str, List[str]] = {
    "生态": ["0301", "0302", "0305", "0307"],
    "农田": ["0101", "0102", "0103"],
    "农业": ["0101", "0102", "0103", "0201", "0204"],
    "村庄": ["2121", "2122"],
    "建设": ["2121", "2122", "2123"],
    "林业": ["0301", "0302", "0305", "0307"],
    "旅游": ["0101", "0201", "0301", "1101"],
    "康养": ["0301", "0302", "1101", "1104"],
}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _default_dlbm_for(name: str) -> List[str]:
    for kw, codes in _DLBM_HINTS.items():
        if kw in name:
            return codes
    return ["0101"]


def extract_vocabulary_deterministic(reports: Dict[str, str]) -> Vocabulary:
    """无 LLM 兜底：从报告分区表提取类别，语义推断颜色与地类线索。"""
    from app.agent.gis.parse.agent import _extract_zone_tables

    categories: List[VocabularyCategory] = []
    seen = set()
    for content in (reports or {}).values():
        for zt in _extract_zone_tables(content):
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
                )
            )
    return Vocabulary(name="l3_extracted", categories=categories)


_VOCAB_PROMPT = """你是村庄规划功能区词汇提取助手。从下列 L3 报告的功能分区内容中提取功能区类别定义。

报告内容：
{reports}

只输出 JSON（不要任何其他文字）：
{{"categories": [{{"name_zh": "生态保护区", "color": "#2d6a4f", "dlbm_hints": ["0301", "0302"], "evidence": "报告原文依据句"}}]}}
要求：
- color 必须是合法的 hex 格式（#RRGGBB），由你自由选择
- dlbm_hints 是推测的地类编码线索（如耕地 0101-0103、林地 0301/0302/0305/0307、宅基地 2121）
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
        categories.append(
            VocabularyCategory(
                code=f"FZ{len(categories) + 1:02d}",
                name_zh=name,
                color=color,
                typing_rules=[TypingRule(kind="dlbm_in", value=hints or _default_dlbm_for(name))],
            )
        )
    return Vocabulary(name="l3_extracted", categories=categories)


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
            vocab = await _extract_vocabulary_llm(llm, reports)
            if vocab.categories:
                return vocab
            logger.info("[VocabExtractor] LLM returned empty categories, falling back to deterministic")
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
