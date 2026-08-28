"""Bounded GROUND reasoning over the already resolved candidate set.

This module is deliberately not another evidence contract.  Retrieval and
geometry remain owned by the existing ``EvidencePacket`` and grounding
contracts.  The model receives only a compact candidate card and can return
only an existing candidate ID; local validation and the deterministic solver
remain authoritative.
"""

from __future__ import annotations

import json
from typing import Any

from app.contracts.ground.grounding_contracts import GroundingResult
from app.contracts.ground.spatial_reference_contracts import (
    CandidateSelectionBatchProposal,
    CandidateSelectionProposal,
    render_candidate_selection_batch_contract,
    spatial_candidate_descriptor,
    spatial_candidate_input_digest,
    validate_spatial_candidate_proposal,
)
from app.modules.ground.target_identity import candidate_id_for_site
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _bounded_refs(values: Any, limit: int = 8) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip()
        for value in list(values or [])[:limit]
        if str(value).strip()
    ))


def _candidate_card(candidate: Any, candidate_id: str) -> str:
    geometry = getattr(candidate, "geometry", None)
    uncertainty = getattr(candidate, "uncertainty", None)
    card = {
        "candidate_id": candidate_id,
        "target_ref": str(getattr(candidate, "target_ref", "") or ""),
        "target_kind": str(getattr(candidate, "target_kind", "unknown") or "unknown"),
        "expected_output_kind": str(
            getattr(candidate, "expected_output_kind", "unknown") or "unknown"
        ),
        "geometry_kind": str(
            getattr(geometry, "kind", "")
            or getattr(candidate, "target_kind", "unknown")
            or "unknown"
        ),
        "schema_status": str(getattr(candidate, "schema_status", "pending") or "pending"),
        "identity_confidence": getattr(candidate, "identity_confidence", None),
        "geometry_confidence": getattr(candidate, "geometry_confidence", None),
        "suitability_score": getattr(candidate, "suitability_score", None),
        "uncertainty_reason": str(getattr(uncertainty, "reason_code", "") or ""),
        "evidence_refs": _bounded_refs(getattr(candidate, "evidence_refs", None)),
        "component_fact_refs": _bounded_refs(
            getattr(candidate, "component_fact_refs", None)
        ),
        "source_parcels": _bounded_refs(getattr(candidate, "source_parcels", None)),
    }
    return json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _query_text(spec: Any, target_id: str) -> str:
    reference = getattr(spec, "reference", None)
    reference_filter = getattr(reference, "filter", None) or {}
    return json.dumps(
        {
            "target_id": target_id,
            "spec_id": str(getattr(spec, "spec_id", "") or ""),
            "type": str(getattr(spec, "type", "") or ""),
            "direction": str(getattr(spec, "direction", "") or ""),
            "relation": str(getattr(spec, "relation", "") or ""),
            "topo": str(getattr(spec, "topo", "") or ""),
            "semantic_terms": _bounded_refs(getattr(spec, "semantic_terms", None)),
            "reference_kind": str(getattr(reference, "kind", "") or ""),
            "reference_name": str(getattr(reference, "name", "") or ""),
            "reference_filter_keys": sorted(str(key) for key in reference_filter)[:16],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _descriptors(candidates: list[Any]) -> tuple[list[Any], list[Any]]:
    selected_candidates: list[Any] = []
    descriptors: list[Any] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            candidate_id = candidate_id_for_site(candidate)
        except Exception:
            continue
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        selected_candidates.append(candidate)
        descriptor = spatial_candidate_descriptor(
            candidate,
            kind=str(getattr(candidate, "target_kind", "candidate") or "candidate"),
        )
        descriptor.candidate_id = candidate_id
        descriptors.append(descriptor)
    return selected_candidates, descriptors


async def reason_ground_candidates(
    result: GroundingResult,
    specs: list[Any],
    *,
    budget: dict[str, Any] | None,
    llm: Any | None = None,
    round_index: int = 1,
) -> dict[str, dict[str, Any]]:
    """Run one bounded batch reasoning call for the current candidate sets.

    The returned mapping is an audit projection.  It is not allowed to create
    candidates or geometry and it is safe for the caller to ignore when the
    provider is disabled/unavailable.  A failed reasoning call therefore does
    not turn a deterministic grounding result into an empty result.  The stage
    calls this once per evidence wave, allowing the model to reconsider a
    target after new candidates, relations or source spans arrive.
    """

    from app.core.llm_config import get_llm_settings
    from app.infrastructure.structured_runtime.facade import (
        LLMCallSpec,
        create_flash_model,
        run_structured,
    )
    from app.spatial.grounding.call_budget import (
        reserve_ground_llm_call,
        run_ground_llm_call,
    )

    settings = get_llm_settings()
    if settings.ground_llm_is_disabled() or not result.candidates:
        return {}
    candidates_by_target: dict[str, list[Any]] = {}
    for candidate in list(result.candidates):
        target_id = str(getattr(candidate, "target_ref", "") or "").strip()
        if target_id:
            candidates_by_target.setdefault(target_id, []).append(candidate)
    if not candidates_by_target:
        return {}
    specs_by_target = {
        str(getattr(spec, "target_id", "") or "").strip(): spec
        for spec in specs
        if str(getattr(spec, "target_id", "") or "").strip()
    }

    prepared: list[dict[str, Any]] = []
    blocks: list[str] = []
    for target_id in sorted(candidates_by_target):
        target_candidates, descriptors = _descriptors(candidates_by_target[target_id])
        if not descriptors:
            continue
        decision_id = f"ground:candidate-set:{target_id}"
        query_text = _query_text(specs_by_target.get(target_id), target_id)
        input_digest = spatial_candidate_input_digest(
            decision_id=decision_id,
            query_text=query_text,
            candidates=descriptors,
        )
        blocks.append(
            "\n".join((
                f"任务 decision_id={decision_id}",
                f"目标语义={query_text}",
                "允许选择的候选集合（只用于判断，不是输出字段）：\n"
                "| candidate_id |\n| --- |\n"
                + "\n".join(
                    f"| {descriptor.candidate_id} |" for descriptor in descriptors
                ),
                f"input_digest={input_digest}",
                "候选卡：",
                "\n".join(
                    _candidate_card(candidate, descriptor.candidate_id)
                    for candidate, descriptor in zip(target_candidates, descriptors)
                ),
            ))
        )
        prepared.append({
            "target_id": target_id,
            "decision_id": decision_id,
            "query_text": query_text,
            "input_digest": input_digest,
            "candidates": target_candidates,
            "descriptors": descriptors,
        })
    if not prepared:
        return {}
    timeout = reserve_ground_llm_call(budget)
    if timeout is None:
        return {}
    prompt = (
        render_candidate_selection_batch_contract()
        + f"\n这是 GROUND 第 {max(1, int(round_index or 1))} 轮候选证据判断。"
        "候选卡不含可执行几何；只能依据已提供的身份、"
        "事实引用和证据引用选择。无法确定时必须 abstain/ambiguous。\n"
        + "\n\n".join(blocks)
    )
    if llm is None:
        try:
            llm = create_flash_model(
                max_tokens=int(settings.ground_max_tokens),
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning("[ground] provider construction failed: %s", type(exc).__name__)
            if budget is not None:
                budget["failed"] = int(budget.get("failed", 0) or 0) + 1
            return {}

    async def _invoke() -> Any:
        return await run_structured(
            LLMCallSpec(
                stage="GROUND",
                contract_key="ground.candidate_selection_batch",
                response_model=CandidateSelectionBatchProposal,
                call_type="closed_set",
                max_retries=int(settings.ground_parse_retries),
                timeout_s=timeout,
                max_tokens=int(settings.ground_max_tokens),
                incomplete_output_max_tokens=int(settings.incomplete_output_max_tokens),
                max_concurrent=settings.stage_concurrency("ground"),
                semaphore_scope="ground",
                temperature=0.1,
                allow_content_json=True,
                timeout_includes_queue=False,
            ),
            [{"role": "user", "content": prompt}],
            context={
                "round": max(1, int(round_index or 1)),
                "target_count": len(prepared),
            },
            llm=llm,
        )

    try:
        response = await run_ground_llm_call(budget, timeout, _invoke)
    except Exception as exc:
        logger.warning("[ground] closed-set reasoning failed: %s", type(exc).__name__)
        return {}

    by_id = {item["decision_id"]: item for item in prepared}
    decisions: dict[str, dict[str, Any]] = {}
    for proposal in list(getattr(response, "decisions", None) or []):
        item = by_id.get(str(getattr(proposal, "decision_id", "") or ""))
        if item is None:
            continue
        try:
            typed = CandidateSelectionProposal.model_validate(
                proposal.model_dump(exclude={"decision_id"})
            )
            decision = validate_spatial_candidate_proposal(
                decision_id=item["decision_id"],
                query_text=item["query_text"],
                candidates=item["descriptors"],
                proposal=typed,
            )
        except Exception as exc:
            logger.warning("[ground] candidate decision validation failed: %s", type(exc).__name__)
            continue
        decisions[item["target_id"]] = {
            "decision_id": item["decision_id"],
            "status": decision.status,
            "selected_candidate_id": decision.selected_candidate_id or "",
            "candidate_set_digest": decision.candidate_set_digest,
            "input_digest": item["input_digest"],
            "reason": decision.reason,
        }
    return decisions


__all__ = ["reason_ground_candidates"]
