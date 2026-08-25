"""Bounded L1 observe/report loop with source-level evidence validation."""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import TypeAdapter

from app.contracts.domain.l1_contracts import L1DimensionPassState, L1SourceIndex
from app.domain.assessment.source_index import render_l1_source_index
from app.domain.assessment.observation_draft import (
    L1PlanningFactDraft,
    L1ReportOutput,
    l1_observation_output_model_for_dimension,
)


CheckpointWriter = Callable[[dict[str, Any]], Awaitable[None] | None]
_FACT_ADAPTER = TypeAdapter(L1PlanningFactDraft)


@dataclass
class L1DimensionRunResult:
    """Final output of one L1 dimension."""

    report_body: str
    observations: list[Any]
    diagnostics: list[str] = field(default_factory=list)
    cursor: L1DimensionPassState | None = None
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _observation_label(observation: Any) -> str:
    for field_name in (
        "name",
        "metric",
        "demand_type",
        "constraint_type",
        "subject",
        "subject_ref",
    ):
        value = str(getattr(observation, field_name, "") or "").strip()
        if value:
            return value[:80]
    return "observation"


def _validate_observation_sources(
    observations: list[Any],
    source_index: L1SourceIndex | None,
) -> tuple[list[Any], list[str]]:
    """Verify fact evidence locators against generic source segments."""

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
                if hasattr(item, "fact_type")
                else _FACT_ADAPTER.validate_python(item)
            )
        except Exception:
            diagnostics.append("observation_source_invalid")
            continue
        ids = [
            str(value).strip()
            for value in observation.source_segment_ids
            if str(value).strip()
        ]
        matched = [segments[value] for value in ids if value in segments]
        unknown = [value for value in ids if value not in segments]
        diagnostics.extend(
            f"observation_source_segment_unknown:{value}" for value in unknown
        )
        quote = str(observation.source_quote or "").strip()
        quote_norm = re.sub(r"\s+", " ", quote)
        evidence_ok = bool(matched and quote_norm) and any(
            quote_norm in re.sub(r"\s+", " ", segment.text)
            for segment in matched
        )
        if not evidence_ok:
            name = _observation_label(observation)
            diagnostics.append(f"observation_source_unverified:{name}")
            observation = observation.model_copy(update={"status": "uncertain"})
        else:
            canonical_refs = list(
                dict.fromkeys(
                    [
                        *observation.source_refs,
                        *(segment.source_ref for segment in matched),
                    ]
                )
            )
            observation = observation.model_copy(update={"source_refs": canonical_refs})
        validated.append(observation)
    return validated, diagnostics


def _dimension_mismatch_diagnostics(
    observations: list[Any],
    *,
    dimension_key: str,
) -> list[str]:
    """Flag globally valid facts that sit outside a dimension's preferred mix."""

    from app.domain.assessment.dimension_contracts import get_dimension_semantic_contract

    allowed_fact_types = {
        str(value).strip()
        for value in (
            get_dimension_semantic_contract(dimension_key, 1).get("l1_fact_types", [])
            or []
        )
        if str(value).strip()
    }
    if not allowed_fact_types:
        return []
    diagnostics: list[str] = []
    for item in observations:
        fact_type = str(getattr(item, "fact_type", "") or "").strip()
        if fact_type and fact_type not in allowed_fact_types:
            diagnostics.append(
                f"l1_dimension_fact_type_mismatch:{dimension_key}:{fact_type}"
            )
    return diagnostics


async def _write_checkpoint(
    writer: CheckpointWriter | None,
    *,
    pass_name: str,
    report_body: str,
    observations: list[Any],
    diagnostics: list[str],
    cursor: L1DimensionPassState,
) -> None:
    if writer is None:
        return
    payload = {
        "pass": pass_name,
        "report_body": report_body,
        "observations": [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in observations
        ],
        "diagnostics": _unique(diagnostics),
        "cursor": cursor.model_dump(mode="json"),
    }
    result = writer(payload)
    if inspect.isawaitable(result):
        await result


async def run_l1_dimension_loop(
    *,
    dimension_key: str,
    prompt: str,
    source_index: L1SourceIndex | None,
    runner_kwargs: dict[str, Any] | None = None,
    checkpoint_writer: CheckpointWriter | None = None,
    resume_payload: dict[str, Any] | None = None,
    previous_cursor: L1DimensionPassState | None = None,
    max_attempts: int = 2,
    max_calls: int = 4,
) -> L1DimensionRunResult:
    """Run a bounded observe → report sequence.

    Semantic facts are produced once. Their own source IDs and quotes are the
    evidence audit surface; no parallel asset/demand register is generated.
    """

    from app.infrastructure.llm.structured import run_structured_output
    from app.domain.assessment.dimension_contracts import (
        render_dimension_semantic_contract,
    )

    source_digest = str(getattr(source_index, "source_digest", "") or "")
    resume_payload = resume_payload or {}
    if previous_cursor is None and isinstance(resume_payload.get("cursor"), dict):
        try:
            previous_cursor = L1DimensionPassState.model_validate(
                resume_payload["cursor"]
            )
        except Exception:
            previous_cursor = None

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
    diagnostics = [
        *resume_diagnostics,
        *list(cursor.diagnostics),
        *[str(value) for value in resume_payload.get("diagnostics", []) or []],
    ]
    retrieval_trace: list[dict[str, Any]] = []
    report_body = str(resume_payload.get("report_body") or "").strip()
    observations: list[Any] = list(resume_payload.get("observations") or [])
    observations, source_diagnostics = _validate_observation_sources(
        observations,
        source_index,
    )
    diagnostics.extend(source_diagnostics)
    diagnostics.extend(
        _dimension_mismatch_diagnostics(
            observations,
            dimension_key=dimension_key,
        )
    )

    if cursor.status == "complete" and report_body:
        return L1DimensionRunResult(
            report_body=report_body,
            observations=observations,
            diagnostics=_unique(diagnostics),
            cursor=cursor,
            retrieval_trace=retrieval_trace,
        )
    if cursor.status == "complete":
        cursor = cursor.model_copy(update={"pass_name": "report", "status": "running"})

    base_kwargs = dict(runner_kwargs or {})
    observe_system = (
        f"【L1 observe pass; dimension_key={dimension_key}】\n"
        "你只负责本维度现状事实结构化。只返回 observations，不返回 report_body；"
        "每条 observation 必须先选择明确的 fact_type。"
        "空间对象、指标、需求、约束、关系、风险和机会都直接写入 observations，"
        "不得另造资产台账、需求台账、coverage 或处理状态。"
        "每条 observation 尽量返回 source_segment_ids 和 source_quote；"
        "没有直接证据就标记 uncertain，不得猜测。"
        "location/relation 只填写来源明确支持的空间线索；"
        "全村指标、全村诉求或政策事实不得为满足格式而编造点位。"
        "同一语义族内的不同子类、指标或风险类型必须保留可区分的 identity；"
        "当同一 scope 和 semantic_type 下出现多个不同量值时，必须在 attributes.metric "
        "或 semantic_type 本身明确写出子类，不要只把区分写在 name/其他 attributes 字段；"
        "例如 forest_area:commercial_forest 与 forest_area:ecological_forest、"
        "cultivation_area:林芝 与 cultivation_area:烤烟、崩塌隐患点与滑坡隐患点，"
        "不能把不同对象压成同一个泛化语义。"
        "fact_type 必须从 spatial_entity/spatial_relation/scoped_metric/demand/"
        "constraint/risk/opportunity/document_observation 中选择；"
        "observations 必须是 JSON 数组；禁止把数组序列化成字符串，禁止把整段 JSON 文本放进 observations 字段；"
        "semantic_type、attributes、value/unit/counting_basis、"
        "related_observation_ids 和 constraint_refs 只填来源明确支持的值。\n\n"
        f"{render_dimension_semantic_contract(dimension_key, 1)}\n\n"
        f"【L1 source index】\n{render_l1_source_index(source_index)}"
    )

    if cursor.pass_name in {"observe", "diagnostic"}:
        observe_response_model = l1_observation_output_model_for_dimension(
            dimension_key
        )
        output = await run_structured_output(
            observe_response_model,
            [
                {"role": "system", "content": observe_system},
                {"role": "user", "content": prompt},
            ],
            **base_kwargs,
        )
        if output is None:
            raise ValueError("L1 observe pass returned no structured output")
        diagnostics.extend(
            str(value)
            for value in (getattr(output, "diagnostics", []) or [])
            if str(value).strip()
        )
        observations, source_diagnostics = _validate_observation_sources(
            list(output.observations or []),
            source_index,
        )
        diagnostics.extend(source_diagnostics)
        diagnostics.extend(
            _dimension_mismatch_diagnostics(
                observations,
                dimension_key=dimension_key,
            )
        )
        cursor = cursor.model_copy(
            update={
                "pass_name": "report",
                "attempt": cursor.attempt + 1,
                "calls_used": cursor.calls_used + 1,
                "status": "running",
            }
        )
        await _write_checkpoint(
            checkpoint_writer,
            pass_name="observe",
            report_body=report_body,
            observations=observations,
            diagnostics=diagnostics,
            cursor=cursor,
        )

    final_status = "complete"
    if not report_body:
        if cursor.calls_used >= cursor.max_calls:
            diagnostics.append("l1_report_synthesis_budget_exhausted")
            final_status = "diagnostic"
        else:
            cursor = cursor.model_copy(
                update={
                    "pass_name": "report",
                    "status": "running",
                    "calls_used": cursor.calls_used + 1,
                }
            )
            report_material = json.dumps(
                {
                    "observations": [
                        item.model_dump(mode="json")
                        if hasattr(item, "model_dump")
                        else item
                        for item in observations
                    ],
                    "diagnostics": _unique(diagnostics),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            report_system = (
                f"【L1 report synthesis pass; dimension_key={dimension_key}】\n"
                "只生成面向规划人员的现状分析正文 report_body。"
                "正文只能解释下面已经通过结构和来源校验的 observations；"
                "不得新增事实、数量、位置、需求点、关系或规划建议。"
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
                retrieval_trace.append(
                    {
                        "pass": "report",
                        "status": "synthesized_from_validated_material",
                        "observation_count": len(observations),
                    }
                )

    cursor = cursor.model_copy(
        update={
            "pass_name": "complete" if final_status == "complete" else "diagnostic",
            "status": final_status,
            "diagnostics": _unique(diagnostics),
        }
    )
    await _write_checkpoint(
        checkpoint_writer,
        pass_name=cursor.pass_name,
        report_body=report_body,
        observations=observations,
        diagnostics=diagnostics,
        cursor=cursor,
    )
    return L1DimensionRunResult(
        report_body=report_body,
        observations=observations,
        diagnostics=_unique(diagnostics),
        cursor=cursor,
        retrieval_trace=retrieval_trace,
    )


__all__ = ["L1DimensionRunResult", "run_l1_dimension_loop"]
