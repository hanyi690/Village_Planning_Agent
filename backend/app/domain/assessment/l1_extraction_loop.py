"""Bounded L1 extract/register/repair loop.

The loop is deliberately local to L1.  It reuses the existing structured
runner and optional evidence adapter, but owns a small pass cursor so an
interrupted dimension can continue from its last successful pass without
replaying the whole source document.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.contracts.domain.l1_contracts import (
    L1DimensionPassState,
    L1InputRegister,
    L1RegisterRow,
)
from app.domain.assessment.input_register import (
    materialize_dimension_register_rows,
    render_l1_source_index,
)
from app.domain.assessment.observation_draft import (
    L1CoverageDecision,
    L1ObservationDraft,
    L1ObservationPassOutput,
    L1ReportOutput,
    L1RegisterPassOutput,
)


EvidenceLookup = Callable[[str, list[str]], Awaitable[str] | str]
CheckpointWriter = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class L1DimensionRunResult:
    """Final output of one dimension loop."""

    report_body: str
    observations: list[Any]
    register_rows: list[L1RegisterRow] = field(default_factory=list)
    coverage: list[L1CoverageDecision] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    cursor: L1DimensionPassState | None = None
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


_FOLLOWUP_STATUSES = {"uncertain", "conflict"}


def _needs_followup(status: str) -> bool:
    """Return whether a row still needs a bounded repair/confirmation pass."""

    return str(status or "").strip() in _FOLLOWUP_STATUSES


def _confirmed_ids(rows: list[L1RegisterRow]) -> list[str]:
    return _unique([
        row.row_id
        for row in rows
        if row.status == "confirmed"
    ])


def _merge_rows(
    existing: list[L1RegisterRow],
    incoming: list[L1RegisterRow],
) -> tuple[list[L1RegisterRow], list[str]]:
    by_id = {row.row_id: row for row in existing}
    diagnostics: list[str] = []
    for row in incoming:
        prior = by_id.get(row.row_id)
        if prior is None:
            by_id[row.row_id] = row
            continue
        if prior.status != "confirmed" and row.status == "confirmed":
            by_id[row.row_id] = row
            continue
        if prior.status == "confirmed" and row.status != "confirmed":
            continue
        if prior.model_dump(mode="json") != row.model_dump(mode="json"):
            diagnostics.append(f"register_row_conflict:{row.row_id}")
    return list(by_id.values()), diagnostics


def _source_index_with_rows(
    source_index: L1InputRegister | None,
    rows: list[L1RegisterRow],
) -> L1InputRegister | None:
    """Expose current-pass registrations to a targeted repair prompt.

    A fresh source index intentionally contains only generic segments.  Once
    the observe pass has materialized a registration, a repair pass still
    needs to see that row's canonical evidence without reparsing the raw
    document.  Merge the typed rows into a prompt-only copy; the persisted
    source index remains segment-only until the dimension artifact is saved.
    """

    if source_index is None or not rows:
        return source_index
    current = {
        row.row_id: row for row in (source_index.current_assets or [])
    }
    demands = {
        row.row_id: row for row in (source_index.demands or [])
    }
    for row in rows:
        target = current if row.ledger_kind == "current_asset" else demands
        target.setdefault(row.row_id, row)
    return source_index.model_copy(update={
        "current_assets": list(current.values()),
        "demands": list(demands.values()),
    })


async def _maybe_lookup(
    lookup: EvidenceLookup | None,
    query: str,
    required: list[str],
) -> str:
    if lookup is None:
        return ""
    result = lookup(query, required)
    if inspect.isawaitable(result):
        result = await result
    return str(result or "")


def _row_names(source_index: L1InputRegister | None, row_ids: list[str]) -> list[str]:
    if source_index is None:
        return []
    wanted = set(row_ids)
    return [
        row.name
        for row in [*(source_index.current_assets or []), *(source_index.demands or [])]
        if row.row_id in wanted and row.name
    ]


def _validate_observation_sources(
    observations: list[Any],
    source_index: L1InputRegister | None,
) -> tuple[list[Any], list[str]]:
    """Verify LLM evidence locators against generic source segments.

    L1 is allowed to discover arbitrary entities from narrative, OCR, tables,
    or mixed material.  The application therefore validates only the
    model-supplied segment identity and quote; it never infers a table row or
    a location from a fixed document format.
    """

    segments = {
        segment.segment_id: segment
        for segment in (getattr(source_index, "source_segments", []) or [])
    }
    if not observations:
        return observations, []
    diagnostics: list[str] = []
    validated: list[Any] = []
    for item in observations:
        try:
            observation = (
                item
                if isinstance(item, L1ObservationDraft)
                else L1ObservationDraft.model_validate(item)
            )
        except Exception:
            diagnostics.append("observation_source_invalid")
            validated.append(item)
            continue
        ids = [str(value).strip() for value in observation.source_segment_ids if str(value).strip()]
        matched = [segments[value] for value in ids if value in segments]
        unknown = [value for value in ids if value not in segments]
        if unknown:
            diagnostics.extend(
                f"observation_source_segment_unknown:{value}" for value in unknown
            )
        quote = str(observation.source_quote or "").strip()
        quote_norm = re.sub(r"\s+", " ", quote)
        evidence_ok = bool(matched and quote_norm)
        if evidence_ok:
            evidence_ok = any(
                quote_norm in re.sub(r"\s+", " ", segment.text)
                for segment in matched
            )
        if not evidence_ok:
            name = str(observation.name or observation.entity_type or "observation")[:80]
            diagnostics.append(f"observation_source_unverified:{name}")
            observation = observation.model_copy(update={"status": "uncertain"})
        elif matched:
            canonical_refs = list(dict.fromkeys(
                [*observation.source_refs, *(segment.source_ref for segment in matched)]
            ))
            observation = observation.model_copy(update={"source_refs": canonical_refs})
        validated.append(observation)
    return validated, diagnostics


async def run_l1_dimension_loop(
    *,
    dimension_key: str,
    prompt: str,
    source_index: L1InputRegister | None,
    runner_kwargs: dict[str, Any] | None = None,
    evidence_lookup: EvidenceLookup | None = None,
    checkpoint_writer: CheckpointWriter | None = None,
    resume_payload: dict[str, Any] | None = None,
    previous_cursor: L1DimensionPassState | None = None,
    max_attempts: int = 2,
    max_calls: int = 4,
) -> L1DimensionRunResult:
    """Run a bounded observe → register → validate → repair loop.

    ``runner_kwargs`` is passed to the existing ``run_structured_output``
    adapter.  The model never writes canonical source fields: materialization
    always resolves returned row IDs against ``source_index``.
    """

    from app.infrastructure.llm.structured import run_structured_output

    source_digest = str(getattr(source_index, "source_digest", "") or "")
    resume_payload = resume_payload or {}
    if previous_cursor is None and isinstance(resume_payload.get("cursor"), dict):
        try:
            previous_cursor = L1DimensionPassState.model_validate(resume_payload["cursor"])
        except Exception:
            previous_cursor = None
    # A cursor is content-addressed to one source index and one dimension.
    # Reusing it against another source would make a successful resume look
    # valid while confirming rows from the wrong document.  Drop the whole
    # resume payload at this boundary and leave a stable diagnostic.
    resume_diagnostics: list[str] = []
    if previous_cursor is not None and (
        previous_cursor.dimension_key != dimension_key
        or (
            source_digest
            and previous_cursor.source_digest
            and previous_cursor.source_digest != source_digest
        )
    ):
        previous_cursor = None
        resume_payload = {}
        resume_diagnostics.append("l1_resume_cursor_stale")
    cursor = previous_cursor or L1DimensionPassState(
        dimension_key=dimension_key,
        source_digest=source_digest,
        max_attempts=max_attempts,
        max_calls=max_calls,
    )
    diagnostics = [*resume_diagnostics, *list(cursor.diagnostics)]
    retrieval_trace: list[dict[str, Any]] = []
    report_body = str(resume_payload.get("report_body") or "").strip()
    observations: list[Any] = list(resume_payload.get("observations") or [])
    register_rows: list[L1RegisterRow] = []
    for raw_row in list(resume_payload.get("register_rows") or []):
        try:
            register_rows.append(L1RegisterRow.model_validate(raw_row))
        except Exception:
            diagnostics.append("resume_register_row_invalid")
    coverage: list[L1CoverageDecision] = []
    for raw_coverage in list(resume_payload.get("coverage") or []):
        try:
            coverage.append(L1CoverageDecision.model_validate(raw_coverage))
        except Exception:
            diagnostics.append("resume_coverage_invalid")
    diagnostics.extend(str(value) for value in resume_payload.get("diagnostics", []) or [])
    observations, observation_diagnostics = _validate_observation_sources(
        observations,
        source_index,
    )
    diagnostics.extend(observation_diagnostics)

    base_kwargs = dict(runner_kwargs or {})
    from app.domain.assessment.dimension_contracts import render_dimension_semantic_contract

    observe_system = (
        f"【L1 observe pass; dimension_key={dimension_key}】\n"
        "你只负责本维度现状观察与原始资料结构化。"
        "只返回 observations/register_rows/coverage，不返回 report_body；"
        "observations 记录原始资料明确出现的空间对象；"
        "register_rows 只有在原始资料明确表达资产/需求登记时才填写；"
        "叙述、OCR、清单或混合资料不得为了填表而硬造 row_id。"
        "current_asset 与 demand 必须严格区分；不能把规划建议当成现状设施。"
        "每个 observation 尽量返回 source_segment_ids 和 source_quote；"
        "没有直接证据就标记 uncertain，不得猜测。"
        "observation_kind 必须区分 place/current_asset/demand/metric/constraint/relation/risk/opportunity/document_observation；"
        "semantic_type、attributes、value/unit/counting_basis、related_observation_ids 和 constraint_refs 只填来源明确支持的值。\n\n"
        f"{render_dimension_semantic_contract(dimension_key, 1)}\n\n"
        f"【L1 source index】\n{render_l1_source_index(source_index)}"
    )

    if cursor.status == "complete" and report_body:
        return L1DimensionRunResult(
            report_body=report_body,
            observations=observations,
            register_rows=register_rows,
            coverage=coverage,
            diagnostics=_unique(diagnostics),
            cursor=cursor,
            retrieval_trace=retrieval_trace,
        )
    if cursor.status == "complete" and not report_body:
        cursor = cursor.model_copy(update={
            "pass_name": "report",
            "status": "running",
        })

    if cursor.pass_name in {"observe", "diagnostic"}:
        output = await run_structured_output(
            L1ObservationPassOutput,
            [
                {"role": "system", "content": observe_system},
                {"role": "user", "content": prompt},
            ],
            **base_kwargs,
        )
        if output is None:
            raise ValueError("L1 observe pass returned no structured output")
        diagnostics.extend(str(value) for value in (getattr(output, "diagnostics", []) or []) if str(value).strip())
        observations, observation_diagnostics = _validate_observation_sources(
            list(output.observations or []),
            source_index,
        )
        diagnostics.extend(observation_diagnostics)
        raw_drafts = list(output.register_rows or [])
        selected_ids = [str(row.row_id) for row in raw_drafts]
        cursor = cursor.model_copy(update={
            "pass_name": "register",
            "attempt": cursor.attempt + 1,
            "calls_used": cursor.calls_used + 1,
            "pending_row_ids": [],
            "status": "running",
        })
        materialized, row_diagnostics = materialize_dimension_register_rows(
            raw_drafts,
            source_index,
            dimension_key,
        )
        register_rows, merge_diagnostics = _merge_rows(register_rows, materialized)
        diagnostics.extend(row_diagnostics)
        diagnostics.extend(merge_diagnostics)
        cursor = cursor.model_copy(update={
            "pending_row_ids": _unique([
                row.row_id
                for row in materialized
                if _needs_followup(row.status)
            ]),
            "confirmed_row_ids": _confirmed_ids(register_rows),
        })
        coverage = list(output.coverage or [])
        if checkpoint_writer is not None:
            checkpoint = {
                "pass": "observe",
                "report_body": report_body,
                "observations": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in observations
                ],
                "register_rows": [row.model_dump(mode="json") for row in register_rows],
                "coverage": [item.model_dump(mode="json") for item in coverage],
                "diagnostics": _unique(diagnostics),
                "cursor": cursor.model_dump(mode="json"),
            }
            result = checkpoint_writer(checkpoint)
            if inspect.isawaitable(result):
                await result

    pending_ids = _unique([
        *cursor.pending_row_ids,
        *[item.row_id for item in coverage if item.status in {"uncertain", "conflict"}],
    ])
    while (
        pending_ids
        and cursor.calls_used < cursor.max_calls
        and cursor.attempt < cursor.max_attempts
    ):
        prompt_index = _source_index_with_rows(source_index, register_rows)
        names = _row_names(prompt_index, pending_ids)
        required = [*names, *diagnostics[-8:]]
        evidence_context = await _maybe_lookup(
            evidence_lookup,
            f"L1 {dimension_key} source-row confirmation: {'、'.join(names)}",
            required,
        )
        if evidence_context:
            retrieval_trace.append({
                "pass": "register",
                "status": "retrieved",
                "row_ids": list(pending_ids),
                "context_chars": len(evidence_context),
            })
        elif evidence_lookup is not None:
            retrieval_trace.append({
                "pass": "register",
                "status": "unavailable_or_empty",
                "row_ids": list(pending_ids),
            })
        register_system = (
            f"【L1 register/repair pass; dimension_key={dimension_key}】\n"
            "只确认下面 pending row_id 的维度归属和不确定性。"
            "返回 register_rows 与 coverage；不得返回列表外的 row_id。"
            "source_index 的 canonical 字段由应用侧写入，模型只提供 status/evidence_note。\n\n"
            f"pending_row_ids={','.join(pending_ids)}\n"
            f"【L1 source index】\n{render_l1_source_index(prompt_index, row_ids=pending_ids)}\n"
            f"【已有校验诊断】\n{'; '.join(diagnostics[-8:]) or '无'}\n"
            f"【检索补充证据（仅作核验线索，不改变 source row）】\n{evidence_context or '无；如原文不足请返回 uncertain/source_exhausted'}"
        )
        followup = await run_structured_output(
            L1RegisterPassOutput,
            [
                {"role": "system", "content": register_system},
                {"role": "user", "content": "请完成 pending row 的确认。"},
            ],
            **base_kwargs,
        )
        if followup is None:
            diagnostics.append("register_pass_empty_output")
            break
        cursor = cursor.model_copy(update={
            "pass_name": "validate",
            "attempt": cursor.attempt + 1,
            "calls_used": cursor.calls_used + 1,
        })
        if checkpoint_writer is not None:
            checkpoint = {
                "pass": "register",
                "report_body": report_body,
                "observations": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in observations
                ],
                "register_rows": [row.model_dump(mode="json") for row in register_rows],
                "coverage": [item.model_dump(mode="json") for item in coverage],
                "diagnostics": _unique(diagnostics),
                "cursor": cursor.model_dump(mode="json"),
            }
            result = checkpoint_writer(checkpoint)
            if inspect.isawaitable(result):
                await result
        followup_ids = [str(item.row_id) for item in followup.register_rows]
        pending_set = set(pending_ids)
        unknown_ids = [row_id for row_id in followup_ids if row_id not in pending_set]
        diagnostics.extend(f"register_row_out_of_scope:{row_id}" for row_id in unknown_ids)
        allowed_drafts = [item for item in followup.register_rows if item.row_id in pending_set]
        materialized, row_diagnostics = materialize_dimension_register_rows(
            allowed_drafts,
            prompt_index,
            dimension_key,
        )
        register_rows, merge_diagnostics = _merge_rows(register_rows, materialized)
        diagnostics.extend(row_diagnostics)
        diagnostics.extend(merge_diagnostics)
        coverage.extend(list(followup.coverage or []))
        still_uncertain = {
            item.row_id
            for item in followup.coverage
            if item.row_id in pending_set and _needs_followup(item.status)
        }
        rejected_ids = {
            value.split(":", 1)[1]
            for value in [*row_diagnostics, *merge_diagnostics, *diagnostics]
            if value.startswith((
                "register_row_unknown:",
                "register_row_ledger_kind_mismatch:",
                "register_row_invalid:",
                "register_row_conflicting_status:",
                "register_row_out_of_scope:",
                "register_row_conflict:",
            ))
            and ":" in value
        }
        if not still_uncertain and not rejected_ids:
            pending_ids = []
        else:
            # A rejected row cannot be repaired by sending the same source
            # index forever.  Remove it from pending, but retain diagnostic
            # status so the dimension terminates fail-closed instead of
            # falsely claiming complete coverage.
            pending_ids = _unique([
                row_id
                for row_id in still_uncertain
                if row_id not in rejected_ids
            ])
        cursor = cursor.model_copy(update={
            "pending_row_ids": pending_ids,
            "confirmed_row_ids": _confirmed_ids(register_rows),
            "rejected_row_ids": _unique([
                item.split(":", 1)[-1]
                for item in diagnostics
                if item.startswith("register_row_")
            ]),
            "diagnostics": _unique(diagnostics),
        })
        if checkpoint_writer is not None:
            checkpoint = {
                "pass": "validate",
                "report_body": report_body,
                "observations": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in observations
                ],
                "register_rows": [row.model_dump(mode="json") for row in register_rows],
                "coverage": [item.model_dump(mode="json") for item in coverage],
                "diagnostics": _unique(diagnostics),
                "cursor": cursor.model_dump(mode="json"),
            }
            result = checkpoint_writer(checkpoint)
            if inspect.isawaitable(result):
                await result
        if not pending_ids:
            break

    if (cursor.calls_used >= cursor.max_calls or cursor.attempt >= cursor.max_attempts) and pending_ids:
        diagnostics.append("l1_pass_call_budget_exhausted")
    structural_diagnostic = any(
        item.startswith((
            "register_row_",
            "l1_resume_",
            "structured_",
            "observation_source_",
        ))
        for item in diagnostics
    )
    final_status = "complete" if not pending_ids and not structural_diagnostic else "diagnostic"
    if not report_body:
        if cursor.calls_used >= cursor.max_calls:
            diagnostics.append("l1_report_synthesis_budget_exhausted")
            final_status = "diagnostic"
        else:
            cursor = cursor.model_copy(update={
                "pass_name": "report",
                "status": "running",
                "calls_used": cursor.calls_used + 1,
            })
            report_material = json.dumps(
                {
                    "observations": [
                        item.model_dump(mode="json")
                        if hasattr(item, "model_dump")
                        else item
                        for item in observations
                    ],
                    "register_rows": [
                        row.model_dump(mode="json") for row in register_rows
                    ],
                    "coverage": [
                        item.model_dump(mode="json")
                        if hasattr(item, "model_dump")
                        else item
                        for item in coverage
                    ],
                    "diagnostics": _unique(diagnostics),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            report_system = (
                f"【L1 report synthesis pass; dimension_key={dimension_key}】\n"
                "只生成面向规划人员的现状分析正文 report_body。"
                "正文必须只解释下面已经通过 source 校验的 observations、登记行和 coverage；"
                "不得新增事实、数量、位置、需求点、关系或规划建议；不返回 observations、register_rows、JSON 数组或代码。"
                "不确定或缺失内容要明确写成证据缺口。\n\n"
                f"{render_dimension_semantic_contract(dimension_key, 1)}\n\n"
                f"【validated L1 material】\n{report_material}"
            )
            report_kwargs = dict(base_kwargs)
            report_kwargs["content_fallback_mode"] = "report_text"
            report_output = await run_structured_output(
                L1ReportOutput,
                [
                    {"role": "system", "content": report_system},
                    {"role": "user", "content": "请根据已验证材料生成现状正文。"},
                ],
                **report_kwargs,
            )
            if report_output is None or not str(report_output.report_body or "").strip():
                diagnostics.append("l1_report_synthesis_empty")
                final_status = "diagnostic"
            else:
                report_body = str(report_output.report_body).strip()
                retrieval_trace.append({
                    "pass": "report",
                    "status": "synthesized_from_validated_material",
                    "observation_count": len(observations),
                    "register_row_count": len(register_rows),
                })
    if any(item.startswith("l1_report_synthesis_") for item in diagnostics):
        final_status = "diagnostic"
    cursor = cursor.model_copy(update={
        "pass_name": "complete" if final_status == "complete" else "diagnostic",
        "status": final_status,
        "pending_row_ids": pending_ids,
        "confirmed_row_ids": _confirmed_ids(register_rows),
        "diagnostics": _unique(diagnostics),
    })
    if checkpoint_writer is not None:
        checkpoint = {
            "pass": cursor.pass_name,
            "report_body": report_body,
            "observations": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in observations
            ],
            "register_rows": [row.model_dump(mode="json") for row in register_rows],
            "coverage": [item.model_dump(mode="json") for item in coverage],
            "diagnostics": _unique(diagnostics),
            "cursor": cursor.model_dump(mode="json"),
        }
        result = checkpoint_writer(checkpoint)
        if inspect.isawaitable(result):
            await result
    return L1DimensionRunResult(
        report_body=report_body,
        observations=observations,
        register_rows=register_rows,
        coverage=coverage,
        diagnostics=_unique(diagnostics),
        cursor=cursor,
        retrieval_trace=retrieval_trace,
    )


__all__ = ["L1DimensionRunResult", "run_l1_dimension_loop"]
