"""Bounded GROUND reasoning over the already resolved candidate set.

This module is deliberately not another evidence contract.  Retrieval and
geometry remain owned by the existing ``EvidencePacket`` and grounding
contracts.  The model receives only a compact candidate card and can return
only an existing candidate ID; local validation and the deterministic solver
remain authoritative.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any

from app.contracts.ground.grounding_contracts import GroundingResult
from app.contracts.ground.spatial_reference_contracts import (
    CandidateSelectionBatchProposal,
    CandidateSelectionProposal,
    GroundTargetPriorityBatchProposal,
    render_candidate_selection_batch_contract,
    render_ground_target_priority_contract,
    spatial_candidate_descriptor,
    spatial_candidate_input_digest,
    validate_spatial_candidate_proposal,
)
from app.modules.ground.target_identity import candidate_id_for_site
from app.infrastructure.context_runtime import build_bounded_table
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _bounded_refs(values: Any, limit: int = 8) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip()
        for value in list(values or [])[:limit]
        if str(value).strip()
    ))


def _candidate_card(candidate: Any, candidate_id: str) -> dict[str, Any]:
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
    return card


def _query_text(spec: Any, target_id: str) -> str:
    reference = getattr(spec, "reference", None)
    reference_filter = getattr(reference, "filter", None) or {}
    _, table = build_bounded_table(
        (
            "target_id", "spec_id", "type", "direction", "relation", "topo",
            "semantic_terms", "reference_kind", "reference_name", "filter_keys",
        ),
        [{
            "target_id": target_id,
            "spec_id": str(getattr(spec, "spec_id", "") or ""),
            "type": str(getattr(spec, "type", "") or ""),
            "direction": str(getattr(spec, "direction", "") or ""),
            "relation": str(getattr(spec, "relation", "") or ""),
            "topo": str(getattr(spec, "topo", "") or ""),
            "semantic_terms": ", ".join(_bounded_refs(getattr(spec, "semantic_terms", None))),
            "reference_kind": str(getattr(reference, "kind", "") or ""),
            "reference_name": str(getattr(reference, "name", "") or ""),
            "filter_keys": ", ".join(sorted(str(key) for key in reference_filter)[:16]),
        }],
        max_rows=1,
        max_chars=2400,
    )
    return table


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
        _, candidate_table = build_bounded_table(
            (
                "candidate_id", "target_ref", "target_kind", "expected_output_kind",
                "geometry_kind", "schema_status", "identity_confidence",
                "geometry_confidence", "suitability_score", "uncertainty_reason",
                "evidence_refs", "component_fact_refs", "source_parcels",
            ),
            [
                _candidate_card(candidate, descriptor.candidate_id)
                for candidate, descriptor in zip(target_candidates, descriptors)
            ],
            max_rows=max(1, len(descriptors)),
            max_chars=18000,
        )
        blocks.append(
            "\n".join((
                f"任务 decision_id={decision_id}",
                "目标语义表：\n" + query_text,
                "候选证据表（只用于判断，不是输出字段）：\n" + candidate_table,
                f"input_digest={input_digest}",
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


async def reason_l1_location_candidates(
    context: Any,
    mentions: list[Any],
    observations: list[Any],
    evidence_packets: dict[str, Any],
    *,
    budget: dict[str, Any] | None,
    round_index: int = 0,
) -> dict[str, dict[str, Any]]:
    """Batch closed-set choices for the direct L1 -> GROUND sidecar.

    One response contains independent decisions for several location work
    items.  A missing or invalid item becomes an explicit ambiguous decision,
    so the resolver does not silently fall back to one serial LLM call per
    target.  The returned map is keyed by the exact candidate input digest and
    is consumed only by ``SpatialResolver``.
    """

    from app.core.llm_config import get_llm_settings
    from app.infrastructure.structured_runtime.facade import (
        LLMCallSpec,
        create_flash_model,
        run_structured,
    )
    from app.spatial.grounding.resolver import SpatialResolver
    from app.spatial.grounding.call_budget import (
        reserve_ground_llm_call,
        run_ground_llm_call,
    )

    settings = get_llm_settings()
    if settings.ground_llm_is_disabled():
        return {}
    resolver = SpatialResolver(context, ground_llm_budget=budget)
    tasks: list[dict[str, Any]] = []
    for mention, observation in zip(mentions, observations):
        observation_id = str(
            getattr(observation, "observation_id", "") or ""
        ).strip()
        packet = (evidence_packets or {}).get(observation_id)
        refs = list(getattr(packet, "candidate_refs", None) or []) if packet else []
        if len(refs) <= 1:
            continue
        spec = None
        try:
            from app.modules.ground.reference_resolution import _mention_spec

            spec = _mention_spec(mention, observation_id, context)
            descriptors = [
                spatial_candidate_descriptor(ref, kind="spatial_candidate")
                for ref in refs
            ]
            candidate_ids = [str(item.candidate_id) for item in descriptors]
            mention_text = str(
                getattr(packet, "request", "") or resolver._spec_mention(spec)
            )
            decision_id = f"spatial-resolver:候选实体:{mention_text}"
            query_text = (
                f"{mention_text}\n"
                f"{resolver._evidence_packet_selection_hints(spec, packet)}"
            )
            input_digest = spatial_candidate_input_digest(
                decision_id=decision_id,
                query_text=query_text,
                candidates=descriptors,
            )
        except Exception as exc:  # noqa: BLE001 - keep the item unresolved
            logger.warning(
                "[ground] L1 batch task preparation failed: %s",
                type(exc).__name__,
            )
            continue
        tasks.append({
            "observation_id": observation_id,
            "mention_text": mention_text,
            "query_text": query_text,
            "decision_id": decision_id,
            "input_digest": input_digest,
            "candidate_ids": candidate_ids,
            "descriptors": descriptors,
            "refs": refs,
        })
    if len(tasks) <= 1:
        return {}

    # Keep each provider request bounded while still amortizing one call over
    # several independent location decisions.
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for task in tasks:
        _, candidate_table = build_bounded_table(
            ("candidate_id", "kind", "label", "metadata"),
            [
                {
                    "candidate_id": descriptor.candidate_id,
                    "kind": descriptor.kind,
                    "label": descriptor.label,
                    "metadata": "; ".join(
                        f"{key}={value}"
                        for key, value in sorted(descriptor.metadata.items())
                        if str(value).strip()
                    ),
                }
                for descriptor in task["descriptors"]
            ],
            max_rows=max(1, len(task["descriptors"])),
            max_chars=10000,
        )
        task["prompt_text"] = "\n".join((
            f"任务 decision_id={task['decision_id']}",
            f"input_digest={task['input_digest']}",
            "允许的候选证据表：",
            candidate_table,
        ))
        if current and (len(current) >= 6 or current_chars + len(task_text) > 24000):
            groups.append(current)
            current = []
            current_chars = 0
        current.append(task)
        current_chars += len(task_text)
    if current:
        groups.append(current)

    decisions: dict[str, dict[str, Any]] = {
        task["input_digest"]: {
            "status": "ambiguous",
            "selected_candidate_id": "",
            "input_digest": task["input_digest"],
            "selection_source": "batch",
            "batch_status": "no_valid_decision",
        }
        for task in tasks
    }
    try:
        llm = create_flash_model(
            max_tokens=min(2400, int(settings.ground_max_tokens)),
            temperature=0.1,
        )
    except Exception as exc:
        logger.warning("[ground] L1 batch provider construction failed: %s", type(exc).__name__)
        return decisions

    async def run_group(group: list[dict[str, Any]]) -> Any:
        timeout = reserve_ground_llm_call(budget)
        if timeout is None:
            return None
        prompt = (
            render_candidate_selection_batch_contract()
            + f"\n这是直接 L1 -> GROUND 的第 {max(1, int(round_index or 1))} 轮。"
            "下面每个任务相互独立；只能从对应任务的 candidate_ids 中选择，"
            "无法验证时必须返回 ambiguous 或 abstain。\n"
            + "\n\n".join(task["prompt_text"] for task in group)
        )

        async def invoke() -> Any:
            return await run_structured(
                LLMCallSpec(
                    stage="GROUND",
                    contract_key="ground.candidate_selection_batch",
                    response_model=CandidateSelectionBatchProposal,
                    call_type="closed_set",
                    max_retries=int(settings.ground_parse_retries),
                    timeout_s=timeout,
                    max_tokens=min(2400, int(settings.ground_max_tokens)),
                    incomplete_output_max_tokens=int(settings.incomplete_output_max_tokens),
                    max_concurrent=settings.stage_concurrency("ground"),
                    semaphore_scope="ground",
                    temperature=0.1,
                    allow_content_json=True,
                    timeout_includes_queue=False,
                ),
                [{"role": "user", "content": prompt}],
                context={"round": round_index, "target_count": len(group), "entry_point": "l1"},
                llm=llm,
            )

        try:
            return await run_ground_llm_call(budget, timeout, invoke)
        except Exception as exc:
            logger.warning("[ground] L1 batch candidate reasoning failed: %s", type(exc).__name__)
            return None

    responses = await __import__("asyncio").gather(*(run_group(group) for group in groups))
    by_decision_id = {task["decision_id"]: task for task in tasks}
    for response in responses:
        for proposal in list(getattr(response, "decisions", None) or []):
            task = by_decision_id.get(str(getattr(proposal, "decision_id", "") or ""))
            if task is None:
                continue
            try:
                typed = CandidateSelectionProposal.model_validate(
                    proposal.model_dump(exclude={"decision_id"})
                )
                decision = validate_spatial_candidate_proposal(
                    decision_id=task["decision_id"],
                    query_text=task["query_text"],
                    candidates=task["descriptors"],
                    proposal=typed,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed per item
                logger.warning("[ground] L1 batch decision rejected: %s", type(exc).__name__)
                continue
            decisions[task["input_digest"]] = {
                "status": decision.status,
                "selected_candidate_id": decision.selected_candidate_id or "",
                "input_digest": task["input_digest"],
                "selection_source": "batch",
                "batch_status": "validated",
            }
    return decisions


async def prioritize_ground_targets(
    specs: list[Any],
    evidence_packets: dict[str, Any],
    *,
    budget: dict[str, Any] | None,
    round_index: int = 1,
) -> dict[str, Any]:
    """Ask the model which admitted targets are most likely to resolve now.

    This is deliberately advisory.  It only reorders already compiled target
    specs; candidate identity, geometry, source membership, and final binding
    remain runtime-owned and are validated by ``SpatialResolver``.
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
    target_items: list[dict[str, Any]] = []
    for spec in specs:
        target_id = str(getattr(spec, "target_id", "") or "").strip()
        if not target_id:
            continue
        packet = (evidence_packets or {}).get(target_id)
        summary = {
            "target_id": target_id,
            "type": str(getattr(spec, "type", "") or ""),
            "semantic_terms": _bounded_refs(getattr(spec, "semantic_terms", None)),
            "reference_name": str(
                getattr(getattr(spec, "reference", None), "name", "") or ""
            )[:120],
            "candidate_count": len(getattr(packet, "candidate_refs", None) or [])
            if packet is not None
            else 0,
            "relation_count": len(getattr(packet, "relation_evidence", None) or [])
            if packet is not None
            else 0,
            "source_span_count": len(getattr(packet, "source_spans", None) or [])
            if packet is not None
            else 0,
            "missing_evidence": _bounded_refs(
                getattr(packet, "missing_evidence", None)
            )
            if packet is not None
            else ["evidence_packet_unavailable"],
            "ambiguity_status": str(
                getattr(packet, "ambiguity_status", "unknown") or "unknown"
            )
            if packet is not None
            else "unknown",
        }
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        target_items.append({
            "target_id": target_id,
            "summary": summary,
            "input_digest": "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        })
    if not target_items or settings.ground_llm_is_disabled():
        return {"ordered_target_ids": [item["target_id"] for item in target_items], "decisions": {}}
    timeout = reserve_ground_llm_call(budget)
    if timeout is None:
        return {"ordered_target_ids": [item["target_id"] for item in target_items], "decisions": {}}

    _, target_table = build_bounded_table(
        (
            "target_id", "input_digest", "type", "semantic_terms", "candidate_count",
            "relation_count", "source_span_count", "missing_evidence", "ambiguity_status",
        ),
        [
            {
                "target_id": item["target_id"],
                "input_digest": item["input_digest"],
                "type": item["summary"]["type"],
                "semantic_terms": ", ".join(item["summary"]["semantic_terms"]),
                "candidate_count": item["summary"]["candidate_count"],
                "relation_count": item["summary"]["relation_count"],
                "source_span_count": item["summary"]["source_span_count"],
                "missing_evidence": ", ".join(item["summary"]["missing_evidence"]),
                "ambiguity_status": item["summary"]["ambiguity_status"],
            }
            for item in target_items
        ],
        max_rows=max(1, len(target_items)),
        max_chars=12000,
    )
    prompt = (
        render_ground_target_priority_contract(item["target_id"] for item in target_items)
        + f"\n这是 GROUND 第 {max(1, int(round_index or 1))} 轮。"
        "请综合每个目标当前的证据包、候选规模、关系线索和缺口，"
        "判断本轮先处理哪些目标更可能得到可验证闭集解析；不要把缺口补成事实。\n"
        + "\n当前目标状态表：\n"
        + target_table
    )
    try:
        llm = create_flash_model(
            max_tokens=min(1200, int(settings.ground_max_tokens)),
            temperature=0.1,
        )

        async def _invoke() -> Any:
            return await run_structured(
                LLMCallSpec(
                    stage="GROUND",
                    contract_key="ground.target_priority",
                    response_model=GroundTargetPriorityBatchProposal,
                    call_type="closed_set",
                    max_retries=int(settings.ground_parse_retries),
                    timeout_s=timeout,
                    max_tokens=min(1200, int(settings.ground_max_tokens)),
                    incomplete_output_max_tokens=int(settings.incomplete_output_max_tokens),
                    max_concurrent=settings.stage_concurrency("ground"),
                    semaphore_scope="ground",
                    temperature=0.1,
                    allow_content_json=True,
                    timeout_includes_queue=False,
                ),
                [{"role": "user", "content": prompt}],
                context={"round": max(1, int(round_index or 1)), "target_count": len(target_items)},
                llm=llm,
            )

        response = await run_ground_llm_call(budget, timeout, _invoke)
    except Exception as exc:
        logger.warning("[ground] target priority reasoning failed: %s", type(exc).__name__)
        return {"ordered_target_ids": [item["target_id"] for item in target_items], "decisions": {}}

    known = {item["target_id"]: item for item in target_items}
    decisions: dict[str, dict[str, str]] = {}
    for proposal in list(getattr(response, "decisions", None) or []):
        target_id = str(getattr(proposal, "target_id", "") or "").strip()
        item = known.get(target_id)
        if item is None or str(getattr(proposal, "input_digest", "") or "") != item["input_digest"]:
            continue
        decisions[target_id] = {
            "priority": str(getattr(proposal, "priority", "low") or "low"),
            "reason": str(getattr(proposal, "reason", "") or "")[:300],
            "input_digest": item["input_digest"],
        }
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    original_order = {item["target_id"]: index for index, item in enumerate(target_items)}
    ordered = sorted(
        (item["target_id"] for item in target_items),
        key=lambda target_id: (
            priority_rank.get(decisions.get(target_id, {}).get("priority", "low"), 2),
            original_order[target_id],
        ),
    )
    return {"ordered_target_ids": ordered, "decisions": decisions}


__all__ = [
    "prioritize_ground_targets",
    "reason_ground_candidates",
    "reason_l1_location_candidates",
]
