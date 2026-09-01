"""Bounded LLM conflict check for unknown DATA temporal roles.

The classifier never assigns feature semantics, entity identity, geometry or
coordinates.  It only decides whether one source is current observation,
planning control, a produced plan, a reference plan, or ambiguous.  Positive
admission requires two exact provider passes over one complete flat profile;
provider failure and incomplete profiles fail closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from app.contracts.data.temporal_role_contracts import (
    SourceTemporalRoleDecision,
    TemporalRoleInputRow,
    TemporalRoleProposal,
    TemporalRoleProposalBatch,
)


PROMPT_VERSION = "data-temporal-role-v1"
_MAX_FIELDS = 64
_MAX_SAMPLE_CHARS = 5_000
_MAX_TEXT_CHARS = 12_000
_ROLE_REASON_CODES = {
    "current_evidence": {"observed_current_state"},
    "planning_control": {"requested_future_action", "hard_constraint"},
    "planned_output": {"produced_plan"},
    "reference_plan": {"reference_plan"},
    "ambiguous": {"insufficient_evidence"},
}


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def temporal_role_input_digest(row: TemporalRoleInputRow) -> str:
    """Return the canonical digest persisted with one classifier input row."""

    return _digest(row.model_dump(mode="json"))


def temporal_role_decision_ref(
    *,
    profile_ref: str,
    declared_channel: str,
    selected_role: str,
    reason_code: str,
    status: str,
    confidence: float,
    input_digest: str,
    raw_output_digest: str,
    prompt_version: str,
    model_id: str,
) -> str:
    """Rebuild the immutable reference used to verify a persisted decision."""

    material = {
        "profile_ref": profile_ref,
        "declared_channel": declared_channel,
        "selected_role": selected_role,
        "reason_code": reason_code,
        "status": status,
        "confidence": confidence,
        "input_digest": input_digest,
        "raw_output_digest": raw_output_digest,
        "prompt_version": prompt_version,
        "model_id": model_id,
    }
    return "temporal-decision:" + _digest(material).removeprefix("sha256:")[:24]


def _sample(value: Any) -> str:
    if value in (None, "", [], {}, ()):
        return ""
    if isinstance(value, (Mapping, list, tuple)):
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
    else:
        text = str(value)
    return " ".join(text.split())[:120]


def _gis_profile(gis_data: Mapping[str, Any]) -> tuple[int, str, str, str, bool]:
    fields: dict[str, list[str]] = defaultdict(list)
    geometry_kinds: set[str] = set()
    record_count = 0

    def observe(row: Mapping[str, Any]) -> None:
        nonlocal record_count
        record_count += 1
        for raw_key, value in row.items():
            key = str(raw_key)
            sample = _sample(value)
            if sample and sample not in fields[key] and len(fields[key]) < 2:
                fields[key].append(sample)
            else:
                fields.setdefault(key, [])

    features = gis_data.get("features")
    if isinstance(features, list):
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            geometry = feature.get("geometry")
            if isinstance(geometry, Mapping):
                geometry_kind = str(geometry.get("type") or "unknown").strip()
                if geometry_kind:
                    geometry_kinds.add(geometry_kind)
            properties = feature.get("properties")
            observe(properties if isinstance(properties, Mapping) else {})
    tables = gis_data.get("tables")
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            for column in table.get("columns") or ():
                fields.setdefault(str(column), [])
            for row in table.get("rows") or ():
                if isinstance(row, Mapping):
                    observe(row)
    if str(gis_data.get("type") or "").casefold() == "rasterresource":
        geometry_kinds.add("raster")
        metadata = {
            str(key): value
            for key, value in gis_data.items()
            if key not in {"data", "pixels", "bytes"}
        }
        observe(metadata)

    ordered_fields = sorted(fields)
    profile_complete = len(ordered_fields) <= _MAX_FIELDS
    selected_fields = ordered_fields[:_MAX_FIELDS]
    sample_values = "; ".join(
        f"{field}={' / '.join(fields[field])}"
        for field in selected_fields
        if fields[field]
    )
    if len(sample_values) > _MAX_SAMPLE_CHARS:
        profile_complete = False
        sample_values = sample_values[:_MAX_SAMPLE_CHARS]
    return (
        record_count,
        ", ".join(sorted(geometry_kinds)),
        ", ".join(selected_fields),
        sample_values,
        profile_complete,
    )


def build_temporal_role_input(
    *,
    source_ref: str,
    declared_channel: str,
    resource_kind: str,
    filename: str = "",
    parsed_text: str = "",
    gis_data: Mapping[str, Any] | None = None,
) -> TemporalRoleInputRow:
    """Build one complete-or-explicitly-incomplete flat source profile."""

    payload = gis_data if isinstance(gis_data, Mapping) else {}
    record_count, geometry_kinds, field_names, samples, complete = _gis_profile(payload)
    text = str(parsed_text or "")
    if len(text) > _MAX_TEXT_CHARS:
        complete = False
        half = _MAX_TEXT_CHARS // 2
        text = text[:half] + "\n...[middle omitted; profile incomplete]...\n" + text[-half:]
    normalized_text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    profile_material = {
        "source_ref": source_ref,
        "declared_channel": declared_channel,
        "resource_kind": resource_kind,
        "filename": filename,
        "record_count": record_count,
        "geometry_kinds": geometry_kinds,
        "field_names": field_names,
        "sample_values": samples,
        "content_excerpt": normalized_text,
        "profile_complete": complete,
    }
    return TemporalRoleInputRow(
        profile_ref="temporal-profile:" + _digest(profile_material).removeprefix("sha256:")[:24],
        **profile_material,
    )


def _prompt(row: TemporalRoleInputRow) -> str:
    from app.infrastructure.context_runtime import build_bounded_table

    columns = (
        "profile_ref",
        "source_ref",
        "declared_channel",
        "resource_kind",
        "filename",
        "record_count",
        "geometry_kinds",
        "field_names",
        "sample_values",
        "content_excerpt",
        "profile_complete",
    )
    _, table = build_bounded_table(
        columns,
        [row.model_dump(mode="json")],
        max_rows=1,
        max_chars=20_000,
    )
    return (
        "### DATA temporal-role source profile\n"
        f"{table}\n\n"
        "只返回一行并逐字复用 profile_ref。selected_role 只能是："
        "current_evidence、planning_control、planned_output、reference_plan、ambiguous。"
        "current_evidence 仅表示已有/现状/基线观察；planning_control 仅表示本次请求、目标或硬约束，"
        "不能是一份已经写好的规划答案；planned_output 表示方案布局、目标年用地、项目清单、"
        "实施安排或其他已经形成的规划结果；reference_plan 表示明确的历史/外部参考规划。"
        "declared_channel 和文件名不是事实证明。若物理字段与样例同样可能来自现状或规划成果，"
        "必须选择 ambiguous。不得输出实体、字段解释、坐标、几何或新的 ID。"
    )


def _proposal_valid(
    proposal: TemporalRoleProposalBatch,
    row: TemporalRoleInputRow,
) -> bool:
    if len(proposal.proposals) != 1:
        return False
    item = proposal.proposals[0]
    return (
        item.profile_ref == row.profile_ref
        and item.reason_code in _ROLE_REASON_CODES[item.selected_role]
    )


def _decision(
    row: TemporalRoleInputRow,
    *,
    selected_role: str,
    reason_code: str,
    status: str,
    confidence: float,
    input_digest: str,
    raw_output_material: list[dict[str, Any]],
    model_id: str,
    provider_pass_count: int,
) -> SourceTemporalRoleDecision:
    raw_output_digest = _digest(raw_output_material)
    return SourceTemporalRoleDecision(
        decision_ref=temporal_role_decision_ref(
            profile_ref=row.profile_ref,
            declared_channel=row.declared_channel,
            selected_role=selected_role,
            reason_code=reason_code,
            status=status,
            confidence=confidence,
            input_digest=input_digest,
            raw_output_digest=raw_output_digest,
            prompt_version=PROMPT_VERSION,
            model_id=model_id,
        ),
        source_ref=row.source_ref,
        profile_ref=row.profile_ref,
        declared_channel=row.declared_channel,
        selected_role=selected_role,
        reason_code=reason_code,
        status=status,
        confidence=confidence,
        profile_complete=row.profile_complete,
        input_digest=input_digest,
        raw_output_digest=raw_output_digest,
        prompt_version=PROMPT_VERSION,
        model_id=model_id,
        provider_pass_count=provider_pass_count,
    )


async def classify_temporal_role_async(
    row: TemporalRoleInputRow,
    *,
    enabled: bool = True,
    llm: Any = None,
    model_id: str = "",
) -> SourceTemporalRoleDecision:
    """Run two bounded passes and retain only exact temporal-role consensus."""

    from app.core.settings import LLM_MODEL

    resolved_model = str(model_id or LLM_MODEL or "configured-default")
    input_digest = temporal_role_input_digest(row)
    if not enabled:
        return _decision(
            row,
            selected_role="ambiguous",
            reason_code="insufficient_evidence",
            status="provider_failed",
            confidence=0.0,
            input_digest=input_digest,
            raw_output_material=[],
            model_id="disabled",
            provider_pass_count=0,
        )

    from app.infrastructure.structured_runtime.facade import LLMCallSpec, run_structured

    messages = [
        {
            "role": "system",
            "content": (
                "你是 DATA 入口的时态角色冲突检查器。输入和输出都是有界平坦表格。"
                "你的决定只能阻止污染或确认声明与内容一致，不能解释业务字段、创建实体、"
                "推断坐标或生成规划。证据不足必须 ambiguous，不能迎合 declared_channel。"
            ),
        },
        {"role": "user", "content": _prompt(row)},
    ]
    passes: list[TemporalRoleProposal] = []
    raw_output_material: list[dict[str, Any]] = []
    for pass_number in range(2):
        try:
            batch = await run_structured(
                LLMCallSpec(
                    stage="DATA",
                    contract_key="data.temporal_role",
                    response_model=TemporalRoleProposalBatch,
                    call_type="closed_set",
                    max_retries=1,
                    timeout_s=90.0,
                    max_tokens=800,
                    incomplete_output_max_tokens=1200,
                    temperature=0.01,
                    allow_content_json=True,
                    input_char_limit=24_000,
                ),
                messages,
                llm=llm,
                context={
                    "profile_ref": row.profile_ref,
                    "pass_number": pass_number + 1,
                },
            )
            raw_output_material.append({
                "pass_number": pass_number + 1,
                "proposals": [
                    item.model_dump(mode="json") for item in batch.proposals
                ],
            })
            if _proposal_valid(batch, row):
                passes.append(batch.proposals[0])
        except Exception as exc:
            raw_output_material.append({
                "pass_number": pass_number + 1,
                "failure": type(exc).__name__,
            })

    if len(passes) != 2:
        return _decision(
            row,
            selected_role="ambiguous",
            reason_code="insufficient_evidence",
            status="provider_failed",
            confidence=0.0,
            input_digest=input_digest,
            raw_output_material=raw_output_material,
            model_id=resolved_model,
            provider_pass_count=len(passes),
        )
    left, right = passes
    if (
        left.selected_role != right.selected_role
        or left.reason_code != right.reason_code
    ):
        return _decision(
            row,
            selected_role="ambiguous",
            reason_code="insufficient_evidence",
            status="ambiguous",
            confidence=0.0,
            input_digest=input_digest,
            raw_output_material=raw_output_material,
            model_id=resolved_model,
            provider_pass_count=2,
        )
    confidence = min(left.confidence, right.confidence)
    positive_admission = left.selected_role in {
        "current_evidence",
        "planning_control",
    }
    accepted = confidence >= 0.7 and (
        row.profile_complete or not positive_admission
    )
    return _decision(
        row,
        selected_role=(left.selected_role if accepted else "ambiguous"),
        reason_code=(left.reason_code if accepted else "insufficient_evidence"),
        status="accepted" if accepted else "ambiguous",
        confidence=confidence,
        input_digest=input_digest,
        raw_output_material=raw_output_material,
        model_id=resolved_model,
        provider_pass_count=2,
    )


__all__ = [
    "PROMPT_VERSION",
    "build_temporal_role_input",
    "classify_temporal_role_async",
    "temporal_role_decision_ref",
    "temporal_role_input_digest",
]
