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
import re
from typing import Any

from pydantic import BaseModel

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
logger = get_logger(__name__)


class _ClassificationResultItem(BaseModel):
    """One target's closed-set classification in the appendix5 namespace."""

    index: int
    selected_code: str
    candidate_codes: list[str] = []
    rationale: str = ""


class _ClassificationResultSet(BaseModel):
    results: list[_ClassificationResultItem] = []




def _extract_json_object(content: str) -> str:
    """Robustly pull the JSON object out of an LLM response."""
    stripped = (content or "").strip()
    # Drop MiniMax reasoning/think blocks before looking for the JSON object.
    stripped = re.sub(r"<think>.*?</think>", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"<\/?think>", "", stripped, flags=re.DOTALL)
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
    names = classification_code_names("appendix5") or {}
    decisions: list[Any] = []
    if llm is None:
        from app.infrastructure.llm.factory import create_llm

        llm = create_llm(temperature=0, max_tokens=4096, streaming=False)
    batch_size = 25
    for batch_start in range(0, len(targets), batch_size):
        batch = targets[batch_start : batch_start + batch_size]
        lines = "\n".join(
            (
                f"{i}. target={t['target_id']} | ??={t['name']} | "
                f"??={t['category']} | ??={t['expected_output_kind']} | "
                f"??={json.dumps((t.get('evidence_refs') or [])[:2], ensure_ascii=False)}"
            )
            for i, t in enumerate(batch, 1)
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
        try:
            structured = llm.with_structured_output(
                _ClassificationResultSet,
                method="function_calling",
            )
            result = await asyncio.wait_for(
                structured.ainvoke(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "Return the classification results only."},
                    ]
                ),
                timeout=180,
            )
            if isinstance(result, _ClassificationResultSet):
                items = result.results
            elif isinstance(result, str):
                items = _ClassificationResultSet.model_validate_json(
                    _extract_json_object(result)
                ).results
            else:
                items = _ClassificationResultSet.model_validate(result).results
        except Exception as exc:
            logger.warning(
                "[classification_generator] structured call failed for batch %d: %s",
                batch_start // batch_size, exc,
            )
            continue
        for item in items:
            try:
                idx = int(getattr(item, "index", 0))
            except (TypeError, ValueError):
                continue
            if not (1 <= idx <= len(batch)):
                continue
            target = batch[idx - 1]
            selected = str(getattr(item, "selected_code", "") or "")
            candidates = [str(c) for c in (getattr(item, "candidate_codes", []) or [])]
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
                    rationale=str(getattr(item, "rationale", "") or "")[:500],
                    status="resolved",
                )
            )
    logger.info(
        "[classification_generator] generated %d decisions for %d targets",
        len(decisions), len(targets),
    )
    return decisions


__all__ = ["generate_classification_decisions"]
