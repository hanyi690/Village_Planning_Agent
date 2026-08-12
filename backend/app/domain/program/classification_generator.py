"""LLM-assisted closed-set classification for unresolved polygon targets.

Design: this is part of L3 PLANNING, not a HUMAN override.  The LLM reads the
target's claim evidence (name / category / scale / evidence refs) and selects
a planning land-use code from the authoritative appendix5 (GHYTBM) closed set
with a rationale.  It never derives a code from a parcel dlbm or a name
crosswalk (see contracts/artifacts/classification_ref.py).  VALIDATE still
audits the produced codes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _build_code_catalog() -> str:
    from app.contracts.artifacts.classification_ref import classification_code_names

    names = classification_code_names("appendix5") or {}
    return "\n".join(f"{code} {name}" for code, name in sorted(names.items()))


def _targets_with_evidence(program: Any) -> list[dict[str, Any]]:
    from app.domain.program.classification import classification_review_targets

    return classification_review_targets(program)


async def generate_classification_decisions(
    program: Any,
    *,
    llm: Any = None,
    max_targets: int = 60,
) -> list[Any]:
    """Generate closed-set appendix5 classification decisions for unresolved targets."""
    from app.contracts.artifacts.classification_ref import (
        ClassificationDecision,
        ClassificationSystem,
        classification_code_names,
    )

    targets = _targets_with_evidence(program)
    if not targets:
        return []
    targets = targets[:max_targets]
    catalog = _build_code_catalog()
    lines = "\n".join(
        (
            f"{i}. target={t['target_id']} | ??={t['name']} | "
            f"??={t['category']} | ??={t['expected_output_kind']} | "
            f"??={json.dumps((t.get('evidence_refs') or [])[:2], ensure_ascii=False)}"
        )
        for i, t in enumerate(targets, 1)
    )
    prompt = (
        "????????????????????????????5?????????????"
        "??????????????????????????????????\n"
        f"{catalog}\n\n"
        "??????\n"
        f"{lines}\n\n"
        '??? JSON?{"results":[{"index":1,"selected_code":"1100","candidate_codes":["1100","1200"],"rationale":"..."}]} '
        "?index ???????selected_code ???? candidate_codes ????????rationale ?????????"
    )
    if llm is None:
        from app.infrastructure.llm.factory import create_llm

        llm = create_llm(temperature=0, max_tokens=4096, streaming=False)
    try:
        resp = await asyncio.wait_for(llm.ainvoke(prompt), timeout=150)
        content = getattr(resp, "content", "") or ""
    except Exception as exc:
        logger.warning("[classification_generator] LLM call failed: %s", exc)
        return []
    stripped = content.strip().strip("`")
    if stripped.lower().startswith("json"):
        stripped = stripped[4:].strip()
    try:
        data = json.loads(stripped)
    except Exception as exc:
        logger.warning("[classification_generator] parse failed: %s", exc)
        return []
    names = classification_code_names("appendix5") or {}
    decisions: list[Any] = []
    for item in data.get("results") or []:
        try:
            idx = int(item.get("index", 0))
        except (TypeError, ValueError):
            continue
        if not (1 <= idx <= len(targets)):
            continue
        target = targets[idx - 1]
        selected = str(item.get("selected_code") or "")
        candidates = [str(c) for c in (item.get("candidate_codes") or [])]
        if selected not in names or selected not in candidates:
            continue
        if not candidates or not all(c in names for c in candidates):
            continue
        decisions.append(
            ClassificationDecision(
                target_id=target["target_id"],
                code_system=ClassificationSystem.APPENDIX5,
                candidate_codes=candidates,
                selected_code=selected,
                decision_mode="llm_l3",
                evidence_refs=list(target.get("evidence_refs") or []),
                rationale=str(item.get("rationale") or "")[:500],
                status="resolved",
            )
        )
    logger.info(
        "[classification_generator] generated %d decisions for %d targets",
        len(decisions), len(targets),
    )
    return decisions


__all__ = ["generate_classification_decisions"]
