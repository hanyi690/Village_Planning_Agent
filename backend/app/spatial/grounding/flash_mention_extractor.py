"""Flash-LLM mention enhancer for GROUND place-name resolution.

Design 12 (PLACE_NAME_RESOLUTION): GROUND resolves closed-set specs through a
deterministic evidence index; mentions that still cannot bind go to the gate.
This module is the *self-service* middle step: before deferring to a HUMAN,
GROUND asks the flash model to rewrite/segment the raw planning prose into a
small list of concrete, locatable mentions (e.g. ``沿石窟河沿岸发展农业`` ->
``石窟河``).  The LLM only produces *text mentions* - it never invents BSMs,
coordinates or geometry.  Final BSMs still come exclusively from the evidence
index / gazetteer / bundle.

Determinism & resume:
- Results are cached by sha256(content) in an in-memory dict plus an optional
  JSON file under the run directory, so LangGraph replay / resume never
  re-invokes the model for the same text.
- If the flash call fails or is disabled, the enhancer returns ``[]`` and
  GROUND falls back to its existing deterministic path (gate + HUMAN).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger
from app.infrastructure.llm.factory import create_flash_llm

logger = get_logger(__name__)

_ROLE_SET = ("village", "water", "road", "facility", "landmark", "area")

_PROMPT_TEMPLATE = """你是村庄规划 GIS 地名提取器。请从给定规划文本中提取所有“可在地图上定位的具体地名实体”。

规则：
1. 只输出地名文本；严禁输出坐标、地块编号、BSM 或任何几何信息。
2. 优先提取：自然村/行政村名、河流水塘等水体名、道路名（含编号，如 122乡道）、设施名（祠堂/学校/广场/村委会/卫生站等）、地标与区域名。
3. 忽略无专名的纯类别词（如“道路”“水塘”“广场”“村内”等）。
4. 忽略方位与动作前缀（沿、村内、现状、新建、改造等），输出核心地名。
5. 每个地名一行，格式：地名|类型
   类型只能是：{roles}
6. 提取不到时输出：NONE

示例：
输入：村内砂石路及机耕路分布区域
输出：砂石路|road
机耕路|road

输入：沿石窟河沿岸发展农业
输出：石窟河|water

输入：主要利益建设，建立新机制
输出：NONE

输入：{text}
输出："""


@dataclass
class MentionCandidate:
    """A text-only mention produced by the enhancer."""

    mention: str = ""
    entity_type: str = "unknown"
    role: str = "unknown"
    evidence: Dict[str, Any] = field(default_factory=dict)


def create_flash_llm_safe():
    """Return a flash LLM or None when the provider is unavailable.

    GROUND enhancement is best-effort; callers must tolerate None.
    """
    try:
        return create_flash_llm(max_tokens=300, temperature=0.1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash-mention] flash LLM unavailable: %s", exc)
        return None


def _content_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class MentionCache:
    """sha256(text) -> parsed mention list, backed by memory + optional JSON."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                self._data = {str(k): v for k, v in loaded.items()}
        except Exception as exc:  # noqa: BLE001 - cache must never break GROUND
            logger.warning("[flash-mention] cache load failed: %s", exc)

    def _flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[flash-mention] cache flush failed: %s", exc)

    def get(self, text: str) -> Optional[List[Dict[str, Any]]]:
        return self._data.get(_content_key(text))

    def put(self, text: str, mentions: List[Dict[str, Any]]) -> None:
        self._data[_content_key(text)] = mentions
        self._flush()


def _parse_response(raw: str) -> List[MentionCandidate]:
    """Parse 'mention|role' lines into candidates, tolerating noise."""
    results: List[MentionCandidate] = []
    seen = set()
    for line in (raw or "").splitlines():
        line = (line or "").strip().strip("`").strip()
        if not line or line.upper() in {"NONE", "无", "NULL"}:
            continue
        # Strict "mention|role" format; prose/noise lines are dropped.  The
        # evidence-index substring matcher still catches valid mentions the
        # model may emit without a role column.
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        mention = parts[0] if parts else ""
        role = parts[1] if len(parts) > 1 else "unknown"
        if not mention or len(mention) < 2 or mention in seen:
            continue
        if mention.startswith("{") or mention.startswith("```"):
            continue
        if role not in _ROLE_SET:
            role = "unknown"
        seen.add(mention)
        results.append(
            MentionCandidate(
                mention=mention,
                entity_type=role,
                role=role,
                evidence={"source": "flash_llm", "raw_line": line[:80]},
            )
        )
    return results


async def extract_mentions(
    text: str,
    cache: Optional[MentionCache] = None,
    llm: Any = None,
) -> List[MentionCandidate]:
    """Enhance raw prose into locatable mentions (text only)."""
    if not text or not text.strip():
        return []
    key_text = text.strip()
    if cache is not None:
        hit = cache.get(key_text)
        if hit is not None:
            return [_candidate_from_dict(item) for item in hit]

    model = llm
    if model is None:
        try:
            model = create_flash_llm(max_tokens=300, temperature=0.1)
        except Exception as exc:  # noqa: BLE001 - no LLM -> deterministic fallback
            logger.warning("[flash-mention] flash LLM unavailable: %s", exc)
            return []

    prompt = _PROMPT_TEMPLATE.format(
        roles="|".join(_ROLE_SET),
        text=key_text[:600],
    )
    try:
        if asyncio.iscoroutinefunction(model.ainvoke):
            response = await model.ainvoke(prompt)
        else:
            response = await asyncio.to_thread(model.invoke, prompt)
    except Exception as exc:  # noqa: BLE001 - never break GROUND on model failure
        logger.warning("[flash-mention] flash LLM call failed: %s", exc)
        return []

    raw = ""
    if hasattr(response, "content"):
        content = response.content
        raw = "".join(content) if isinstance(content, list) else str(content or "")
    else:
        raw = str(response or "")
    mentions = _parse_response(raw)
    if cache is not None:
        cache.put(key_text, [_candidate_to_dict(m) for m in mentions])
    return mentions


def _candidate_to_dict(c: MentionCandidate) -> Dict[str, Any]:
    return {
        "mention": c.mention,
        "entity_type": c.entity_type,
        "role": c.role,
        "evidence": c.evidence,
    }


def _candidate_from_dict(item: Dict[str, Any]) -> MentionCandidate:
    return MentionCandidate(
        mention=str(item.get("mention") or ""),
        entity_type=str(item.get("entity_type") or "unknown"),
        role=str(item.get("role") or "unknown"),
        evidence=dict(item.get("evidence") or {}),
    )


__all__ = [
    "MentionCandidate",
    "MentionCache",
    "extract_mentions",
]