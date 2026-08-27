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
    l1_observation_provider_model_for_dimension,
    normalize_l1_observation_provider_output,
)


CheckpointWriter = Callable[[dict[str, Any]], Awaitable[None] | None]
_FACT_ADAPTER = TypeAdapter(L1PlanningFactDraft)
_L1_OBSERVE_PAGE_CHARS = 6200


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


def _source_pages(
    source_index: L1SourceIndex | None,
    *,
    max_chars: int = _L1_OBSERVE_PAGE_CHARS,
) -> list[L1SourceIndex | None]:
    """Partition source segments into deterministic, resumable observe pages.

    The complete source index is still processed across the pages.  Paging is
    only an output/latency boundary: it prevents one provider response from
    having to enumerate every fact in every source segment at once.
    """

    if source_index is None or not source_index.source_segments:
        return [source_index]
    pages: list[L1SourceIndex] = []
    current: list[Any] = []
    current_chars = 0
    for segment in source_index.source_segments:
        segment_chars = max(1, len(segment.text))
        if current and current_chars + segment_chars > max_chars:
            pages.append(source_index.model_copy(update={"source_segments": current}))
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += segment_chars
    if current:
        pages.append(source_index.model_copy(update={"source_segments": current}))
    return pages or [source_index]


def _observation_key(observation: Any) -> str:
    payload = (
        observation.model_dump(mode="json")
        if hasattr(observation, "model_dump")
        else observation
    )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_observations(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """Merge page results without collapsing distinct evidence-backed facts."""

    merged = list(existing)
    known = {_observation_key(item) for item in merged}
    for item in incoming:
        key = _observation_key(item)
        if key not in known:
            merged.append(item)
            known.add(key)
    return merged


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
            diagnostics.append(f"observation_source_quarantined:{name}")
            continue
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

    from app.infrastructure.llm.manager import LLMCallSpec, get_llm_manager
    from app.domain.assessment.dimension_contracts import (
        get_dimension_semantic_contract,
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
    llm_manager = get_llm_manager()

    def _call_spec(
        response_model: type[Any],
        *,
        contract_key: str,
        call_type: str,
        max_tokens: int,
    ) -> LLMCallSpec:
        return LLMCallSpec(
            stage="L1",
            contract_key=contract_key,
            response_model=response_model,
            call_type=call_type,
            max_retries=int(base_kwargs.get("max_retries", 0)),
            timeout_s=float(base_kwargs.get("timeout", 480.0)),
            max_tokens=max(1, int(max_tokens)),
            incomplete_output_max_tokens=int(
                base_kwargs.get("incomplete_output_max_tokens", max_tokens)
            ),
            max_concurrent=int(base_kwargs.get("max_concurrent", 1)),
            semaphore_scope=str(base_kwargs.get("semaphore_scope", "l1")),
            transient_retries=int(base_kwargs.get("transient_retries", 0)),
            transient_retry_backoff_s=float(
                base_kwargs.get("transient_retry_backoff_s", 0.0)
            ),
            temperature=float(base_kwargs.get("temperature", 0.3)),
            allow_content_json=bool(base_kwargs.get("allow_content_json", False)),
            timeout_includes_queue=bool(
                base_kwargs.get("timeout_includes_queue", False)
            ),
        )
    semantic_contract = get_dimension_semantic_contract(dimension_key, 1)
    allowed_fact_types = tuple(semantic_contract.get("l1_fact_types", []) or [])
    allowed_fact_types_json = json.dumps(
        list(allowed_fact_types), ensure_ascii=False, separators=(",", ":")
    )
    source_pages = _source_pages(source_index)
    source_page_count = len(source_pages)
    if cursor.source_page_count != source_page_count:
        cursor = cursor.model_copy(
            update={"source_page_count": source_page_count}
        )
    if cursor.source_page_index >= source_page_count:
        cursor = cursor.model_copy(
            update={"pass_name": "report", "source_page_index": source_page_count}
        )
    observe_system = (
        f"【L1 observe pass; dimension_key={dimension_key}】\n"
        "本 pass 只负责 typed observations，不负责报告写作；响应字段、类型和默认值只以声明的 "
        "L1ObservationProviderOutput 工具 schema 为准。不要把 JSON 写入 message.content，不要输出 "
        "report_body、Markdown、正文或额外根字段。observations 必须是数组；没有内容时使用 schema 默认值。"
        f"每条 observation 的 fact_type 只能逐字选择本维度闭集 {allowed_fact_types_json}；"
        "不同 fact_type 只填写其 schema 声明的专属字段，不要混用其他分支字段。"
        "不要按数量配额截断或扩写；逐条保留本页来源实际支持的观察，"
        "同一来源句中的同一语义只保留一条。"
        "共享证据字段只填来源明确支持的值；尽量提供 source_segment_ids 和 source_quote，"
        "没有直接证据就标记 uncertain，不得猜测。"
        "字符串字段没有值时使用空字符串，数组字段没有值时使用空数组，不要返回 null；"
        "attributes 的值使用标量或可序列化的 JSON 值，不要把列表写入字符串字段。"
        "空间 locator 只记录来源明确支持的粗粒度地点/关系，不填写坐标或几何；"
        "全村指标、诉求或政策事实不需要为了格式强行添加点位。"
        "同一语义族内不同子类或量值必须保留可区分的 semantic_type 或 attributes.metric，"
        "不能压成泛化事实。\n\n"
        f"{render_dimension_semantic_contract(dimension_key, 1)}\n\n"
    )

    if cursor.pass_name in {"observe", "diagnostic"}:
        observe_response_model = l1_observation_provider_model_for_dimension(
            dimension_key
        )
        while cursor.pass_name in {"observe", "diagnostic"}:
            if cursor.calls_used >= cursor.max_calls:
                diagnostics.append("l1_observe_page_budget_exhausted")
                break
            page_index = min(cursor.source_page_index, source_page_count - 1)
            page_system = (
                observe_system
                + f"【L1 source page {page_index + 1}/{source_page_count}】\n"
                "本次只处理这一页中的 source_segment；没有出现在本页的来源不得引用。"
                "若本页没有本维度事实，返回空 observations 数组。\n\n"
                "【L1 source index】\n"
                + render_l1_source_index(source_pages[page_index])
            )
            provider_output = await llm_manager.run_structured(
                _call_spec(
                    observe_response_model,
                    contract_key="l1.observe",
                    call_type="semantic",
                    max_tokens=int(base_kwargs.get("max_tokens", 1)),
                ),
                [
                    {"role": "system", "content": page_system},
                    {"role": "user", "content": prompt},
                ],
            )
            output = normalize_l1_observation_provider_output(
                dimension_key,
                provider_output,
            )
            if output is None:
                raise ValueError("L1 observe pass returned no structured output")
            diagnostics.extend(
                str(value)
                for value in (getattr(output, "diagnostics", []) or [])
                if str(value).strip()
            )
            page_observations, source_diagnostics = _validate_observation_sources(
                list(output.observations or []),
                source_pages[page_index],
            )
            diagnostics.extend(source_diagnostics)
            diagnostics.extend(
                _dimension_mismatch_diagnostics(
                    page_observations,
                    dimension_key=dimension_key,
                )
            )
            observations = _merge_observations(observations, page_observations)
            next_page_index = page_index + 1
            page_complete = next_page_index >= source_page_count
            cursor = cursor.model_copy(
                update={
                    "pass_name": "report" if page_complete else "observe",
                    "attempt": cursor.attempt + 1,
                    "calls_used": cursor.calls_used + 1,
                    "source_page_index": next_page_index,
                    "source_page_count": source_page_count,
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
            if page_complete:
                break

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
            if report_kwargs.get("report_max_tokens") is not None:
                report_kwargs["max_tokens"] = report_kwargs["report_max_tokens"]
                report_kwargs.pop("report_max_tokens", None)
            report_output = await llm_manager.run_structured(
                _call_spec(
                    L1ReportOutput,
                    contract_key="l1.report",
                    call_type="report",
                    max_tokens=int(
                        report_kwargs.get(
                            "max_tokens",
                            report_kwargs.get("report_max_tokens", 1),
                        )
                    ),
                ),
                [
                    {"role": "system", "content": report_system},
                    {"role": "user", "content": "请根据已验证材料生成现状正文。"},
                ],
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
