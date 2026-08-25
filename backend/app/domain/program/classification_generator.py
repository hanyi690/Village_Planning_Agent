"""LLM-assisted closed-set classification for unresolved polygon targets.

Design: this is part of L3 PLANNING, not a HUMAN override.  The LLM reads the
target's claim evidence (name / category / scale / evidence refs) and selects
a planning land-use code from the authoritative appendix5 (GHYTBM) closed set
with a rationale.  It never derives a code from a parcel dlbm or a name
crosswalk (see contracts/artifacts/classification_ref.py).  VALIDATE still
audits the produced codes.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class _ClassificationResultItem(BaseModel):
    """One target's closed-set classification in the appendix5 namespace."""

    model_config = ConfigDict(extra="forbid", strict=True)

    index: int
    selected_code: str
    rationale: str = ""


class _ClassificationResultSet(BaseModel):
    """Strict object wrapper for one complete classification batch."""

    model_config = ConfigDict(extra="forbid", strict=True)

    results: list[_ClassificationResultItem]


def _build_code_catalog() -> str:
    from app.contracts.artifacts.classification_ref import classification_code_names

    names = classification_code_names("appendix5") or {}
    return "\n".join(f"{code} {name}" for code, name in sorted(names.items()))


def _targets_with_evidence(program: Any) -> list[dict[str, Any]]:
    from app.domain.program.classification import classification_review_targets

    return classification_review_targets(program)


def _validated_batch_items(
    items: list[Any],
    *,
    batch_size: int,
    code_names: dict[str, str],
) -> list[_ClassificationResultItem]:
    """Validate one complete closed-set result batch before applying any item."""

    by_index: dict[int, _ClassificationResultItem] = {}
    errors: list[str] = []
    for raw in items:
        item = (
            raw
            if isinstance(raw, _ClassificationResultItem)
            else _ClassificationResultItem.model_validate(raw)
        )
        if not 1 <= item.index <= batch_size:
            errors.append(f"index {item.index} out of range")
            continue
        if item.index in by_index:
            errors.append(f"duplicate index {item.index}")
            continue
        if item.selected_code not in code_names:
            errors.append(f"index {item.index} unknown selected_code {item.selected_code}")
            continue
        by_index[item.index] = item
    missing = sorted(set(range(1, batch_size + 1)) - set(by_index))
    if missing:
        errors.append(f"missing indices {missing}")
    if errors:
        raise ValueError("; ".join(errors))
    return [by_index[index] for index in range(1, batch_size + 1)]


async def generate_classification_decisions(
    program: Any,
    *,
    llm: Any = None,
    max_targets: int = 200,
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
    names = classification_code_names("appendix5") or {}
    decisions: list[Any] = []
    from app.infrastructure.llm.structured import run_structured_output
    batch_size = 6
    for batch_start in range(0, len(targets), batch_size):
        batch = targets[batch_start : batch_start + batch_size]
        lines = "\n".join(
            (
                f"{i}. target={t['target_id']} | 名称={t['name']} | "
                f"类别={t['category']} | 产出={t['expected_output_kind']} | "
                f"依据={json.dumps((t.get('evidence_refs') or [])[:2], ensure_ascii=False)}"
            )
            for i, t in enumerate(batch, 1)
        )
        prompt = (
            "你是村庄规划用地分类助手。对下列每个规划项目，从权威附录５（广东省村庄规划用地分类）"
            "闭集编码中选择唯一的规划用地编码（规划用途，不是现状地类）。编码表：\n"
            f"{catalog}\n\n"
            "待分类项目：\n"
            f"{lines}\n\n"
            '只输出 JSON：{"results":[{"index":1,"selected_code":"1100","rationale":"..."}]} '
            "（index 对应上面编号；必须恰好返回每个 1..N 的 index 各一次，不得缺失、重复或新增；"
            "selected_code 必须来自编码表；rationale 可省略或保持简短；只输出 results 根对象）"
        )
        items: list[Any] = []
        validation_feedback = ""
        for attempt in range(3):
            try:
                result = await run_structured_output(
                    _ClassificationResultSet,
                    [
                            {"role": "system", "content": prompt},
                            {
                                "role": "user",
                                "content": (
                                    "Return the complete classification results only."
                                    + (
                                        " The previous result was rejected: "
                                        + validation_feedback
                                        + ". Repair every listed error and return all indices."
                                        if validation_feedback
                                        else ""
                                    )
                                ),
                            },
                    ],
                    max_retries=1,
                    timeout=180,
                    temperature=0.0,
                    max_tokens=4096,
                    llm=llm,
                )
                if result is None:
                    raise ValueError("provider returned None")
                if isinstance(result, _ClassificationResultSet):
                    items = result.results
                else:
                    items = _ClassificationResultSet.model_validate(result).results
                items = _validated_batch_items(
                    list(items or []),
                    batch_size=len(batch),
                    code_names=names,
                )
                break
            except Exception as exc:
                validation_feedback = str(exc)[:1000]
                items = []
                logger.warning(
                    "[classification_generator] structured call failed for batch %d attempt %d: %s",
                    batch_start // batch_size, attempt + 1, exc,
                )
                continue
        if not items:
            logger.warning(
                "[classification_generator] batch %d produced no items after retries",
                batch_start // batch_size,
            )
            continue
        for item in items:
            idx = item.index
            target = batch[idx - 1]
            selected = item.selected_code
            decisions.append(
                ClassificationDecision(
                    target_id=target["target_id"],
                    code_system=ClassificationSystem.APPENDIX5,
                    candidate_codes=[selected],
                    selected_code=selected,
                    decision_mode="llm_l3",
                    evidence_refs=list(target.get("evidence_refs") or []),
                    rationale=str(item.rationale or "")[:500],
                    status="resolved",
                )
            )
    logger.info(
        "[classification_generator] generated %d decisions for %d targets",
        len(decisions), len(targets),
    )
    return decisions


__all__ = ["generate_classification_decisions"]
