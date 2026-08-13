"""Flash-LLM semantic place-entity extractor for GROUND place-name resolution.

Design 12 (PLACE_NAME_RESOLUTION): GROUND resolves closed-set specs through a
deterministic evidence index; mentions that still cannot bind go to the gate.
This module is the *self-service* middle step: before deferring to a HUMAN,
GROUND asks the flash model to rewrite/segment the raw planning prose into a
small list of typed place entities (mention / entity_type / role /
canonical_name / confidence).  The LLM only produces *semantic text and closed
set labels* - it never invents BSMs, coordinates or geometry.  Final BSMs still
come exclusively from the evidence index / gazetteer / bundle.

The primary path uses ``with_structured_output(function_calling)`` so GROUND
receives typed entities it can match to specific named features (road/water/
facility/village) instead of falling back to a whole-DLMC parcel class.  When
the provider does not support structured output, the enhancer falls back to a
``mention|role`` text-line protocol and parses it deterministically.

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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.infrastructure.logging import get_logger
from app.infrastructure.llm.factory import create_flash_llm

logger = get_logger(__name__)

_ROLE_SET = ("village", "water", "road", "facility", "landmark", "area")


class SemanticPlaceEntity(BaseModel):
    """One typed place entity produced by the flash model.

    ``mention`` is the raw span; ``canonical_name`` is the core locatable name
    with prefixes/suffixes stripped.  Neither field is a BSM or coordinate.
    """

    mention: str = ""
    entity_type: str = "unknown"
    role: str = "unknown"
    canonical_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticPlaceEntitySet(BaseModel):
    # MiniMax function-calling sometimes wraps the array in a JSON string;
    # the caller unwraps it exactly like the L3 classification helper.
    entities: list[SemanticPlaceEntity] | str = []


_STRUCTURED_SYSTEM = """你是村庄规划 GIS 地名实体提取器。请从给定规划文本中提取所有“可在地图上定位的具体地名实体”。

规则：
1. 只输出地名文本与语义类型；严禁输出坐标、地块编号、BSM 或任何几何信息。
2. 优先提取：自然村/行政村名、河流水塘等水体名、道路名（含编号，如 122乡道）、设施名（祠堂/学校/广场/村委会/卫生站等）、地标与区域名。
3. 忽略无专名的纯类别词（如“道路”“水塘”“广场”“村内”等）。
4. 忽略方位与动作前缀（沿、村内、现状、新建、改造等）。
5. role 只能是：{roles}
6. 提取不到时返回空列表。

对每个实体，mention 保留规划文本原文片段，canonical_name 为去掉前后缀后的核心地名，confidence 为 0-1 的提取置信度。

待提取文本：{text}"""


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
    """A typed place entity produced by the enhancer."""

    mention: str = ""
    entity_type: str = "unknown"
    role: str = "unknown"
    canonical_name: str = ""
    confidence: float = 0.0
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


def _extract_json_object(content: str) -> str:
    """Robustly pull the JSON object out of an LLM response."""
    stripped = (content or "").strip()
    stripped = re.sub(r"<think>.*?</think>", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"</?think>", "", stripped, flags=re.DOTALL)
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    if stripped.lower().startswith("json"):
        stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


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
                canonical_name=mention,
                confidence=0.0,
                evidence={"source": "flash_llm", "raw_line": line[:80]},
            )
        )
    return results


def _parse_structured_payload(payload: Any) -> List[MentionCandidate]:
    """Parse a structured-output response into typed ``MentionCandidate``s.

    Handles ``SemanticPlaceEntitySet``, a JSON-string-wrapped payload (MiniMax),
    a dict, and a list.  Invalid roles/mentions are dropped, never fabricated.
    """
    raw: Any = None
    if isinstance(payload, SemanticPlaceEntitySet):
        raw = payload.entities
    elif isinstance(payload, str):
        try:
            raw = SemanticPlaceEntitySet.model_validate_json(
                _extract_json_object(payload)
            ).entities
        except Exception:
            return []
    else:
        try:
            raw = SemanticPlaceEntitySet.model_validate(payload).entities
        except Exception:
            return []
    if isinstance(raw, str):
        try:
            raw = SemanticPlaceEntitySet.model_validate_json(
                _extract_json_object(raw)
            ).entities
        except Exception:
            return []
    if not isinstance(raw, list):
        return []

    results: List[MentionCandidate] = []
    seen = set()
    for item in raw:
        try:
            entity = (
                item
                if isinstance(item, SemanticPlaceEntity)
                else SemanticPlaceEntity.model_validate(item)
            )
        except Exception:
            continue
        mention = (entity.mention or "").strip()
        if not mention or len(mention) < 2 or mention in seen:
            continue
        role = entity.role if entity.role in _ROLE_SET else "unknown"
        canonical = (entity.canonical_name or "").strip() or mention
        seen.add(mention)
        results.append(
            MentionCandidate(
                mention=mention,
                entity_type=entity.entity_type if entity.entity_type else role,
                role=role,
                canonical_name=canonical,
                confidence=float(entity.confidence or 0.0),
                evidence={"source": "flash_llm_structured"},
            )
        )
    return results


async def _extract_structured(
    model: Any, key_text: str
) -> Optional[List[MentionCandidate]]:
    """Run structured output; return None when the provider can't do it."""
    try:
        structured = model.with_structured_output(
            SemanticPlaceEntitySet, method="function_calling"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[flash-mention] structured output unsupported: %s", exc)
        return None
    prompt = _STRUCTURED_SYSTEM.format(
        roles="|".join(_ROLE_SET), text=key_text[:600]
    )
    try:
        if asyncio.iscoroutinefunction(getattr(structured, "ainvoke", None)):
            response = await structured.ainvoke(
                [{"role": "system", "content": prompt}]
            )
        else:
            response = await asyncio.to_thread(
                structured.invoke, [{"role": "system", "content": prompt}]
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash-mention] structured call failed: %s", exc)
        return None
    return _parse_structured_payload(response)


async def extract_mentions(
    text: str,
    cache: Optional[MentionCache] = None,
    llm: Any = None,
) -> List[MentionCandidate]:
    """Enhance raw prose into typed place entities (text + closed-set labels)."""
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

    # Primary: typed structured output.  Fall back to the text-line protocol
    # only when structured output is unsupported or produced nothing.
    mentions = await _extract_structured(model, key_text)
    if not mentions:
        prompt = _PROMPT_TEMPLATE.format(
            roles="|".join(_ROLE_SET),
            text=key_text[:600],
        )
        try:
            if asyncio.iscoroutinefunction(model.ainvoke):
                response = await model.ainvoke(prompt)
            else:
                response = await asyncio.to_thread(model.invoke, prompt)
        except Exception as exc:  # noqa: BLE001
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
        "canonical_name": c.canonical_name,
        "confidence": c.confidence,
        "evidence": c.evidence,
    }


def _candidate_from_dict(item: Dict[str, Any]) -> MentionCandidate:
    return MentionCandidate(
        mention=str(item.get("mention") or ""),
        entity_type=str(item.get("entity_type") or "unknown"),
        role=str(item.get("role") or "unknown"),
        canonical_name=str(item.get("canonical_name") or ""),
        confidence=float(item.get("confidence") or 0.0),
        evidence=dict(item.get("evidence") or {}),
    )


__all__ = [
    "MentionCandidate",
    "MentionCache",
    "SemanticPlaceEntity",
    "SemanticPlaceEntitySet",
    "extract_mentions",
]
