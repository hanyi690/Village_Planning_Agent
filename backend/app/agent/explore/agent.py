"""Independent Explore Flash agent — text -> ExplorationInstructionCollection.

The agent is intentionally bounded: it produces evidence and candidate entity
references, never final planning geometry.  Its deterministic baseline makes
offline/replay runs reproducible; an optional Flash model can refine the same
contract without changing the downstream Binder boundary.

Consumes the access-tools layer (``app.tools.access``) for any bundle data
needed by downstream stages, and the stable KG boundary
(``app.modules.kg.require_session_kg`` / ``query_session_template``) for session
KG interactions.

Path placement note
-------------------
This implementation is sourced from the ``origin/agent/kg-schema-gis-handoff-
20260730`` branch (commit 25e24847) but relocated under
``app/agent/explore/`` to keep the local framework layout (the local
``summaries.py`` keeps providing deterministic dimension cognition).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.agent.explore.contracts import (
    ExplorationInstruction,
    ExplorationInstructionCollection,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DOMAIN_KEYWORDS = {
    "road": ("道路", "路", "连通", "通达", "拓宽", "硬化"),
    "facility": ("设施", "服务中心", "卫生", "学校", "广场", "停车"),
    "landuse": ("用地", "地块", "耕地", "建设用地"),
    "zone": ("分区", "三区", "红线", "边界", "管控"),
    "regulation": ("禁止", "不得", "应当", "限制", "保护"),
    "axis": ("轴", "廊道", "发展带", "景观带"),
    "project": ("产业园", "种植园", "基地", "加工坊", "作坊", "民宿", "集市", "美食坊",
                "科普园", "示范区", "养殖场", "合作社", "培育基地", "功能分区", "项目库",
                "保育区", "开发区", "生活区", "旅游区"),
}
_BSM_RE = re.compile(r"(?:BSM|bsm|标识码)\s*[:：#]?\s*([A-Za-z0-9_-]{2,})")


class SessionKGQuery:
    """KG tool facade that cannot fall back to another session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def kg(self) -> Any:
        from app.modules.kg import require_session_kg

        return require_session_kg(self.session_id)

    def query(self, template_name: str, **params: Any) -> List[Dict[str, Any]]:
        from app.modules.kg import query_session_template

        return query_session_template(self.session_id, template_name, **params)


def _chunks(text: str) -> Iterable[Dict[str, Any]]:
    title = ""
    page = 1
    ordinal = 0
    for raw in re.split(r"\f", text or ""):
        for part in re.split(r"(?=^#{1,6}\s+)", raw, flags=re.M):
            part = part.strip()
            if not part:
                continue
            heading = re.match(r"^#{1,6}\s+(.+)$", part, flags=re.M)
            if heading:
                title = heading.group(1).strip()
            ordinal += 1
            yield {"chunk_id": f"chunk-{ordinal:04d}", "title": title, "page": page, "text": part}
        page += 1


def _domain_for(text: str) -> Optional[str]:
    scores = {
        domain: sum(text.count(keyword) for keyword in keywords)
        for domain, keywords in _DOMAIN_KEYWORDS.items()
    }
    domain, score = max(scores.items(), key=lambda item: item[1])
    return domain if score else None


def _action_for(domain: str, text: str) -> str:
    if domain == "road":
        if any(word in text for word in ("拓宽", "加宽")):
            return "widen"
        if any(word in text for word in ("修复", "整治", "硬化")):
            return "repair"
        return "new_connection" if any(word in text for word in ("新建", "连接", "连通")) else "road_requirement"
    if "新建" in text:
        return "create"
    if "保留" in text:
        return "preserve"
    return "constrain" if domain == "regulation" else "plan"


def _mentions(text: str) -> List[str]:
    # Quoted/place-like phrases give the Binder stable aliases, while BSM is
    # captured separately and never fabricated by the model.
    quoted = re.findall(r"[“\"]([^”\"]{2,40})[”\"]", text)
    named = re.findall(r"([\u4e00-\u9fff]{2,20}(?:村|路|桥|河|塘|学校|卫生室|广场|中心|园|坊|基地|集))", text)
    return list(dict.fromkeys([*quoted, *named]))[:12]


class ExploreFlashAgent:
    """Small tool-capable exploration unit with a deterministic safe baseline.

    Lifecycle:
      1. Construction (cheap).  Reads ``GIS_EXPLORE_LLM_ENABLED`` and
         instantiates the Flash model only when enabled — when disabled the
         agent falls back to the deterministic baseline so offline/replay
         sessions stay reproducible.
      2. ``explore(planning_text)``: requires the session KG up front (a
         readiness check and a guard against a stale / most-recent graph),
         then emits ``ExplorationInstruction`` records per matched chunk.
    """

    def __init__(self, *, session_id: str, village_name: str = "", llm: Any = None):
        self.session_id = session_id
        self.village_name = village_name
        self.kg_tools = SessionKGQuery(session_id)
        if llm is None:
            # Kept opt-in via env so offline/replay sessions retain
            # deterministic behavior; production enables this independently of
            # the PARSE formatter model via GIS_EXPLORE_LLM_ENABLED.
            from app.core.settings import GIS_EXPLORE_LLM_ENABLED
            llm = self.create_flash_llm() if GIS_EXPLORE_LLM_ENABLED else None
        self.llm = llm

    @staticmethod
    def create_flash_llm() -> Any:
        """Construct the independently configured Flash model on demand."""
        from app.core.llm import create_llm
        from app.core.settings import (
            GIS_EXPLORE_MAX_TOKENS,
            GIS_EXPLORE_MODEL,
            GIS_EXPLORE_TEMPERATURE,
        )

        return create_llm(
            model=GIS_EXPLORE_MODEL,
            temperature=GIS_EXPLORE_TEMPERATURE,
            max_tokens=GIS_EXPLORE_MAX_TOKENS,
            streaming=False,
        )

    def explore(self, planning_text: str) -> ExplorationInstructionCollection:
        # Require the current session KG before examining text.  This is both a
        # readiness check and a guard against a stale / most-recent graph.
        _ = self.kg_tools.kg
        instructions: List[ExplorationInstruction] = []
        for chunk in _chunks(planning_text):
            domain = _domain_for(chunk["text"])
            if domain is None:
                continue
            bsms = list(dict.fromkeys(_BSM_RE.findall(chunk["text"])))
            mentions = _mentions(chunk["text"])
            unresolved = not bool(bsms)
            instructions.append(
                ExplorationInstruction(
                    instruction_id=f"EXP-{len(instructions) + 1:04d}",
                    source_chunk_id=chunk["chunk_id"],
                    section_title=chunk["title"],
                    source_page=chunk["page"],
                    evidence_text=chunk["text"],
                    domain=domain,  # type: ignore[arg-type]
                    action=_action_for(domain, chunk["text"]),
                    entity_mentions=mentions,
                    entity_types=[domain],
                    requested_bundle_queries=["bsm_geometry", "entity_candidates", "planning_zone", "construction_permission"],
                    candidate_bsm_list=bsms,
                    constraints=[{"kind": "textual", "text": chunk["text"]}] if domain == "regulation" else [],
                    confidence=0.82 if bsms else 0.55,
                    requires_human_confirmation=unresolved,
                )
            )
        return ExplorationInstructionCollection(
            session_id=self.session_id,
            village_name=self.village_name,
            kg_session_ref=self.session_id,
            instructions=instructions,
        )


def explore_planning_text(
    *, session_id: str, village_name: str, planning_text: str, output_path: Optional[Path] = None
) -> ExplorationInstructionCollection:
    result = ExploreFlashAgent(session_id=session_id, village_name=village_name).explore(planning_text)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = [
    "ExploreFlashAgent",
    "SessionKGQuery",
    "explore_planning_text",
]