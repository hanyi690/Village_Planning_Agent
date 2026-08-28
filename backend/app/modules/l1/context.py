"""Bounded L1 observe/report loop with source-level evidence validation."""

from __future__ import annotations

import html
import hashlib
import inspect
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import TypeAdapter

from app.contracts.l1.l1_contracts import (
    L1DimensionInput,
    L1DimensionPassState,
    L1InputContext,
    L1SourceIndex,
)
from app.modules.l1.retrieval import render_l1_source_index
from app.infrastructure.context_runtime import project_source_index
from app.modules.l1.observation_draft import (
    L1PlanningFactDraft,
    L1DimensionCheckpoint,
    L1DimensionOutput,
    L1DisplayProjection,
    L1SemanticOutput,
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
    input_context: L1InputContext | None = None
    output: L1DimensionOutput | None = None


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


def build_l1_input_context(
    *,
    dimension_key: str,
    source_index: L1SourceIndex | None,
    session_id: str = "",
    source_index_ref: Any = "",
    allowed_fact_types: tuple[str, ...] | list[str] | None = None,
    source_section_hints: tuple[str, ...] | list[str] | None = None,
) -> L1InputContext:
    """Build the single dimension-level context shared by L1 input/output."""

    if allowed_fact_types is None:
        from app.modules.l1.dimension_contracts import (
            get_dimension_semantic_contract,
        )

        allowed_fact_types = tuple(
            get_dimension_semantic_contract(dimension_key, 1).get(
                "l1_fact_types", []
            )
            or []
        )
    if isinstance(source_index_ref, dict):
        source_index_ref = source_index_ref.get("descriptor_digest") or source_index_ref.get(
            "digest"
        ) or ""
    source_index = project_source_index(source_index, source_section_hints or ())
    pages = _source_pages(source_index)
    projection_digest = hashlib.sha256(
        json.dumps(
            [segment.segment_id for segment in (source_index.source_segments if source_index else [])],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return L1InputContext(
        session_id=str(session_id or ""),
        dimension_key=dimension_key,
        source_index_ref=str(source_index_ref or ""),
        source_digest=str(getattr(source_index, "source_digest", "") or ""),
        source_projection_digest="sha256:" + projection_digest,
        source_page_count=len(pages),
        allowed_fact_types=tuple(allowed_fact_types or ()),
    )


def _page_input(
    context: L1InputContext,
    page_index: int,
    source_page: L1SourceIndex | None,
) -> L1DimensionInput:
    """Create and validate one source-page projection from the shared context."""

    segment_ids = tuple(
        segment.segment_id
        for segment in (getattr(source_page, "source_segments", []) or [])
    )
    return L1DimensionInput(
        context=context,
        page_index=page_index,
        page_segment_ids=segment_ids,
        source_page=source_page,
    )


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


def _canonical_source_text(value: Any) -> str:
    """Canonicalize literal source text for quote matching only.

    This removes presentation noise introduced by MinerU/HTML table markup and
    normalizes Unicode punctuation.  It does not summarize, tokenize, or apply
    fuzzy matching: the resulting quote must still be a literal substring of
    the current source segment.
    """

    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", "", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\ufeff", "").replace("\u00a0", " ")
    text = text.translate(str.maketrans({
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "－": "-",
    }))
    return re.sub(r"\s+", "", text)


def _match_source_segments(
    observation: Any,
    source_segments: list[Any],
) -> tuple[list[Any], str, bool]:
    """Match a literal quote against the claimed segment and its neighbors.

    Source indexing can split one original sentence at a bounded character
    boundary. A quote may therefore span adjacent segments even when the
    provider cites only one anchor segment. The returned match is still a
    literal substring of the current page and is expanded to every segment
    that supplies that substring for provenance.
    """

    ids = {
        str(value).strip()
        for value in (getattr(observation, "source_segment_ids", []) or [])
        if str(value).strip()
    }
    segments = [
        segment
        for segment in (source_segments or [])
        if str(getattr(segment, "segment_id", "") or "").strip()
    ]
    matched = [
        segment
        for segment in segments
        if str(getattr(segment, "segment_id", "") or "").strip() in ids
    ]
    quote = str(getattr(observation, "source_quote", "") or "").strip()
    if not matched or not quote:
        return matched, "", False

    def matches(parts: list[Any]) -> str:
        raw_text = re.sub(
            r"\s+",
            " ",
            "".join(str(getattr(part, "text", "") or "") for part in parts),
        )
        raw_quote = re.sub(r"\s+", " ", quote)
        if raw_quote and raw_quote in raw_text:
            return "raw"
        canonical_text = _canonical_source_text(
            "".join(str(getattr(part, "text", "") or "") for part in parts)
        )
        canonical_quote = _canonical_source_text(quote)
        if canonical_quote and canonical_quote in canonical_text:
            return "canonical"
        return ""

    direct_kind = matches(matched)
    if direct_kind:
        return matched, direct_kind, False

    by_source: dict[str, list[Any]] = {}
    for segment in segments:
        source_key = str(getattr(segment, "source_key", "") or "")
        by_source.setdefault(source_key, []).append(segment)
    for source_key, grouped in by_source.items():
        grouped.sort(key=lambda item: int(getattr(item, "start_char", 0) or 0))
        anchors = [
            index
            for index, segment in enumerate(grouped)
            if str(getattr(segment, "segment_id", "") or "").strip() in ids
        ]
        for anchor in anchors:
            for start in range(max(0, anchor - 1), anchor + 1):
                for end in range(anchor, min(len(grouped), anchor + 3)):
                    window = grouped[start : end + 1]
                    if len(window) <= 1:
                        continue
                    kind = matches(window)
                    if kind:
                        return window, kind, True
    return matched, "", False


def _validate_observation_sources(
    observations: list[Any],
    source_index: L1SourceIndex | None,
) -> tuple[list[Any], list[str], int]:
    """Verify fact evidence locators against generic source segments."""

    page_segments = list(getattr(source_index, "source_segments", []) or [])
    segments = {segment.segment_id: segment for segment in page_segments}
    if not observations:
        return observations, [], 0
    diagnostics: list[str] = []
    validated: list[Any] = []
    rejected_count = 0
    for item in observations:
        try:
            observation = (
                item
                if hasattr(item, "fact_type")
                else _FACT_ADAPTER.validate_python(item)
            )
        except Exception:
            diagnostics.append("observation_source_invalid")
            rejected_count += 1
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
        matched, evidence_kind, spans_segments = _match_source_segments(
            observation,
            page_segments,
        )
        raw_evidence_ok = evidence_kind == "raw"
        canonical_evidence_ok = evidence_kind == "canonical"
        if spans_segments:
            diagnostics.append(
                f"observation_source_quote_spans_segments:{_observation_label(observation)}"
            )
        if canonical_evidence_ok and not raw_evidence_ok:
            diagnostics.append(
                f"observation_source_quote_normalized:{_observation_label(observation)}"
            )
        evidence_ok = raw_evidence_ok or canonical_evidence_ok
        if not evidence_ok:
            name = _observation_label(observation)
            diagnostics.append(f"observation_source_quarantined:{name}")
            rejected_count += 1
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
    return validated, diagnostics, rejected_count


def _dimension_mismatch_diagnostics(
    observations: list[Any],
    *,
    dimension_key: str,
) -> list[str]:
    """Flag globally valid facts that sit outside a dimension's preferred mix."""

    from app.modules.l1.dimension_contracts import get_dimension_semantic_contract

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
    input_context: L1InputContext,
    rejected_count: int,
) -> None:
    if writer is None:
        return
    semantic = L1SemanticOutput(
        context=input_context,
        observations=observations,
        diagnostics=_unique(diagnostics),
        accepted_count=len(observations),
        rejected_count=max(0, int(rejected_count)),
        status=(
            cursor.status
            if cursor.status in {"running", "complete", "diagnostic"}
            else "diagnostic"
        ),
    )
    output = L1DimensionOutput(
        semantic=semantic,
        display=L1DisplayProjection(
            report_body=report_body,
            input_digest=input_context.input_digest,
            source_observation_count=len(observations),
        ),
    )
    checkpoint = L1DimensionCheckpoint(
        context=input_context,
        output=output,
        cursor=cursor,
    )
    payload = {
        "l1_checkpoint": checkpoint.model_dump(mode="json"),
        "pass": pass_name,
        "cursor": cursor.model_dump(mode="json"),
    }
    result = writer(payload)
    if inspect.isawaitable(result):
        await result


def _build_l1_output(
    *,
    input_context: L1InputContext,
    report_body: str,
    observations: list[Any],
    diagnostics: list[str],
    rejected_count: int,
    status: str,
) -> L1DimensionOutput:
    """Build the only L1 output envelope exposed beyond the loop."""

    normalized_status = status if status in {"running", "complete", "diagnostic"} else "diagnostic"
    return L1DimensionOutput(
        semantic=L1SemanticOutput(
            context=input_context,
            observations=observations,
            diagnostics=_unique(diagnostics),
            accepted_count=len(observations),
            rejected_count=max(0, int(rejected_count)),
            status=normalized_status,
        ),
        display=L1DisplayProjection(
            report_body=report_body,
            input_digest=input_context.input_digest,
            source_observation_count=len(observations),
        ),
    )


def _deterministic_report_body(
    dimension_key: str,
    observations: list[Any],
) -> str:
    """Assemble display text from already-admitted typed observations only."""

    if not observations:
        return (
            f"【{dimension_key}】未从本次准入源段形成可用 typed observation；"
            "相关内容保持为证据缺口，未生成推断事实。"
        )

    def _cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value).replace("|", "\\|").replace("\n", " ")

    rows = [
        f"【{dimension_key}】已准入 {len(observations)} 条 typed observation；"
        "以下内容仅来自已通过结构与来源校验的记录。",
        "| observation_id | fact_type | semantic_type | description | value | source_segment_ids | source_quote | status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in observations:
        raw = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        if not isinstance(raw, dict):
            continue
        rows.append(
            "| "
            + " | ".join(
                _cell(raw.get(key))
                for key in (
                    "observation_id",
                    "fact_type",
                    "semantic_type",
                    "description",
                    "value",
                    "source_segment_ids",
                    "source_quote",
                    "status",
                )
            )
            + " |"
        )
    return "\n".join(rows)


async def run_l1_dimension_loop(
    *,
    dimension_key: str,
    source_index: L1SourceIndex | None,
    input_context: L1InputContext | None = None,
    prompt: str = "",
    runner_kwargs: dict[str, Any] | None = None,
    checkpoint_writer: CheckpointWriter | None = None,
    resume_payload: dict[str, Any] | None = None,
    previous_cursor: L1DimensionPassState | None = None,
    max_attempts: int = 2,
    max_calls: int = 4,
    quality_feedback: str = "",
) -> L1DimensionRunResult:
    """Run a bounded observe → report sequence.

    Semantic facts are produced once. Their own source IDs and quotes are the
    evidence audit surface; no parallel asset/demand register is generated.
    """

    from app.infrastructure.structured_runtime.facade import LLMCallSpec, run_structured
    from app.modules.l1.dimension_contracts import (
        get_dimension_semantic_contract,
        render_dimension_semantic_contract,
    )

    semantic_contract = get_dimension_semantic_contract(dimension_key, 1)
    allowed_fact_types = tuple(semantic_contract.get("l1_fact_types", []) or [])
    source_index = project_source_index(
        source_index,
        semantic_contract.get("source_section_hints", []) or [],
    )
    source_digest = str(getattr(source_index, "source_digest", "") or "")
    source_pages = _source_pages(source_index)
    source_page_count = len(source_pages)
    if input_context is None:
        input_context = build_l1_input_context(
            dimension_key=dimension_key,
            source_index=source_index,
            allowed_fact_types=allowed_fact_types,
            source_section_hints=semantic_contract.get("source_section_hints", []) or [],
        )
    else:
        if input_context.dimension_key != dimension_key:
            raise ValueError("L1 input context dimension does not match the run")
        if (
            input_context.source_digest
            and source_digest
            and input_context.source_digest != source_digest
        ):
            raise ValueError("L1 input context source digest does not match the run")
        if input_context.allowed_fact_types and tuple(
            input_context.allowed_fact_types
        ) != allowed_fact_types:
            raise ValueError("L1 input context fact types do not match the run")
        input_context = L1InputContext.model_validate({
            **input_context.model_dump(mode="python"),
            "source_digest": source_digest,
            "source_page_count": source_page_count,
            "allowed_fact_types": allowed_fact_types,
            "input_digest": "",
        })

    resume_payload = dict(resume_payload or {})
    checkpoint_payload = resume_payload.get("l1_checkpoint") or resume_payload.get(
        "checkpoint"
    )
    if checkpoint_payload:
        try:
            checkpoint = L1DimensionCheckpoint.model_validate(checkpoint_payload)
            if checkpoint.context.input_digest != input_context.input_digest:
                resume_payload = {}
            else:
                resume_payload = {
                    "report_body": checkpoint.output.display.report_body,
                    "observations": checkpoint.output.semantic.observations,
                    "diagnostics": checkpoint.output.semantic.diagnostics,
                    "rejected_count": checkpoint.output.semantic.rejected_count,
                    "cursor": checkpoint.cursor.model_dump(mode="json"),
                }
        except Exception:
            resume_payload = {}

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
        or (
            previous_cursor.input_digest
            and previous_cursor.input_digest != input_context.input_digest
        )
    ):
        previous_cursor = None
        resume_payload = {}
        resume_diagnostics.append("l1_resume_cursor_stale")

    cursor = previous_cursor or L1DimensionPassState(
        dimension_key=dimension_key,
        source_digest=source_digest,
        input_digest=input_context.input_digest,
        max_attempts=max_attempts,
        max_calls=max_calls,
    )
    if cursor.input_digest != input_context.input_digest:
        cursor = cursor.model_copy(update={"input_digest": input_context.input_digest})
    diagnostics = [
        *resume_diagnostics,
        *list(cursor.diagnostics),
        *[str(value) for value in resume_payload.get("diagnostics", []) or []],
    ]
    retrieval_trace: list[dict[str, Any]] = []
    report_body = str(resume_payload.get("report_body") or "").strip()
    observations: list[Any] = list(resume_payload.get("observations") or [])
    rejected_count = max(0, int(resume_payload.get("rejected_count") or 0))
    observations, source_diagnostics, source_rejected_count = _validate_observation_sources(
        observations,
        source_index,
    )
    rejected_count += source_rejected_count
    diagnostics.extend(source_diagnostics)
    diagnostics.extend(
        _dimension_mismatch_diagnostics(
            observations,
            dimension_key=dimension_key,
        )
    )
    page_failures = any(
        str(value).startswith("l1_observe_page_failed:")
        for value in diagnostics
    )

    if cursor.status == "complete" and report_body:
        output = _build_l1_output(
            input_context=input_context,
            report_body=report_body,
            observations=observations,
            diagnostics=diagnostics,
            rejected_count=rejected_count,
            status="complete",
        )
        return L1DimensionRunResult(
            report_body=report_body,
            observations=observations,
            diagnostics=_unique(diagnostics),
            cursor=cursor,
            retrieval_trace=retrieval_trace,
            input_context=input_context,
            output=output,
        )
    if cursor.status == "complete":
        cursor = cursor.model_copy(update={"pass_name": "report", "status": "running"})

    base_kwargs = dict(runner_kwargs or {})
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
    allowed_fact_types_json = json.dumps(
        list(allowed_fact_types), ensure_ascii=False, separators=(",", ":")
    )
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
        "分支专属字段不是可选说明：spatial_entity 必须同时提供非空 entity_type/name，"
        "spatial_relation 必须同时提供非空 subject_ref/predicate/object_ref，"
        "scoped_metric 必须同时提供非空 metric/scope，demand、constraint、risk、"
        "opportunity 和 document_observation 也必须填写各自的非空语义字段；不能用"
        "description 或 semantic_type 代替缺失的分支字段。"
        "不要按数量配额截断或扩写；逐条保留本页来源实际支持的观察，"
        "同一来源句中的同一语义只保留一条。"
        "共享证据字段只填来源明确支持的值；尽量提供 source_segment_ids 和 source_quote，"
        "没有直接证据就标记 uncertain，不得猜测。"
        "字符串字段没有值时使用空字符串，数组字段没有值时使用空数组，不要返回 null；"
        "对于来源明确出现的地点或空间对象，使用 schema 已声明的 spatial_mentions 输出"
         "独立语义工作项，并在其中使用 scope_mentions 保留名称、角色、关系和来源；"
        "这些字段只能表达粗空间线索，不得输出坐标、几何、BSM、候选实体或任何执行字段。"
        "全村指标、诉求或政策事实不需要为了格式强行添加点位。"
        "同一语义族内不同子类或量值必须保留可区分的 semantic_type 或 value/unit，"
        "不能压成泛化事实。\n\n"
        f"{render_dimension_semantic_contract(dimension_key, 1)}\n\n"
    )
    if str(quality_feedback or "").strip():
        observe_system += (
            "【上一轮质量门反馈】\n"
            "这是同一维度、同一 source input 的定向重试。只修复下面列出的条目级缺陷；"
            "不得凭空增加对象、数量、地点、关系或证据。已被隔离的行不得通过改名或猜测补回；"
            "如果来源不能支持完整字段，返回空 observations 或保留为可审计缺口。\n"
            f"{str(quality_feedback).strip()[:2400]}\n\n"
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
            page_input = _page_input(
                input_context,
                page_index,
                source_pages[page_index],
            )
            page_context_json = json.dumps(
                {
                    "context": page_input.context.model_dump(mode="json"),
                    "page_index": page_input.page_index,
                    "page_segment_ids": list(page_input.page_segment_ids),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            page_system = (
                observe_system
                + "【L1DimensionInput context】\n"
                + page_context_json
                + "\n"
                + f"【L1 source page {page_index + 1}/{source_page_count}】\n"
                "本次只处理这一页中的 source_segment；没有出现在本页的来源不得引用。"
                "若本页没有本维度事实，返回空 observations 数组。\n\n"
                "【L1 source index】\n"
                + render_l1_source_index(source_pages[page_index])
            )
            try:
                provider_output = await run_structured(
                    _call_spec(
                        observe_response_model,
                        contract_key="l1.observe",
                        call_type="semantic",
                        max_tokens=int(
                            base_kwargs.get(
                                "observe_max_tokens",
                                min(int(base_kwargs.get("max_tokens", 1)), 6144),
                            )
                        ),
                    ),
                    [
                        {"role": "system", "content": page_system},
                        {
                            "role": "user",
                            "content": "请仅依据 system 中声明的 L1DimensionInput 输出 typed observations。",
                        },
                    ],
                )
                output = normalize_l1_observation_provider_output(
                    dimension_key,
                    provider_output,
                )
                if output is None:
                    raise ValueError("L1 observe pass returned no structured output")
            except Exception as exc:
                # A page is an independent semantic transaction.  Preserve
                # all already validated pages, advance the durable cursor, and
                # expose this page as a diagnostic instead of turning a local
                # provider/JSON failure into a whole-layer pause.
                from app.infrastructure.structured_runtime.parser import (
                    structured_failure_code,
                    structured_failure_summary,
                )

                code = structured_failure_code(exc) or type(exc).__name__
                summary = structured_failure_summary(exc)
                page_failures = True
                diagnostics.append(
                    f"l1_observe_page_failed:{page_index}:{code}:{summary[:240]}"
                )
                retrieval_trace.append(
                    {
                        "pass": "observe",
                        "page_index": page_index,
                        "status": "diagnostic",
                        "failure_code": code,
                    }
                )
                next_page_index = page_index + 1
                page_complete = next_page_index >= source_page_count
                cursor = cursor.model_copy(
                    update={
                        "pass_name": "report" if page_complete else "observe",
                        "attempt": cursor.attempt + 1,
                        "calls_used": cursor.calls_used + 1,
                        "source_page_index": next_page_index,
                        "source_page_count": source_page_count,
                        "status": "diagnostic",
                        "diagnostics": _unique(diagnostics),
                    }
                )
                await _write_checkpoint(
                    checkpoint_writer,
                    pass_name="observe",
                    report_body=report_body,
                    observations=observations,
                    diagnostics=diagnostics,
                    cursor=cursor,
                    input_context=input_context,
                    rejected_count=rejected_count,
                )
                if page_complete:
                    break
                continue
            diagnostics.extend(
                str(value)
                for value in (getattr(output, "diagnostics", []) or [])
                if str(value).strip()
            )
            quarantined = list(getattr(output, "quarantined_observations", []) or [])
            rejected_count += len(quarantined)
            quarantine_paths: dict[str, int] = {}
            for item in quarantined:
                paths = getattr(item, "error_paths", None)
                if isinstance(item, dict):
                    paths = item.get("error_paths")
                for path in paths or []:
                    key = str(path).strip()
                    if key:
                        quarantine_paths[key] = quarantine_paths.get(key, 0) + 1
            if quarantine_paths:
                diagnostics.append(
                    "l1_quarantine_error_paths:"
                    + ",".join(
                        f"{key}={count}"
                        for key, count in sorted(quarantine_paths.items())
                    )
                )
            page_observations, source_diagnostics, page_rejected_count = _validate_observation_sources(
                list(output.observations or []),
                source_pages[page_index],
            )
            rejected_count += page_rejected_count
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
                input_context=input_context,
                rejected_count=rejected_count,
            )
            if page_complete:
                break

    final_status = "diagnostic" if page_failures else "complete"
    if not report_body:
        report_body = _deterministic_report_body(dimension_key, observations)
        diagnostics.append("l1_report_assembled_from_validated_observations")
        retrieval_trace.append(
            {
                "pass": "report",
                "status": "assembled_from_validated_material",
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
        input_context=input_context,
        rejected_count=rejected_count,
    )
    output = _build_l1_output(
        input_context=input_context,
        report_body=report_body,
        observations=observations,
        diagnostics=diagnostics,
        rejected_count=rejected_count,
        status=final_status,
    )
    return L1DimensionRunResult(
        report_body=report_body,
        observations=observations,
        diagnostics=_unique(diagnostics),
        cursor=cursor,
        retrieval_trace=retrieval_trace,
        input_context=input_context,
        output=output,
    )


__all__ = [
    "L1DimensionRunResult",
    "build_l1_input_context",
    "run_l1_dimension_loop",
]
