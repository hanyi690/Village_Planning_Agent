"""Ingress role assessment before a source can enter current-world DATA.

Transport buckets are declarations, not proof.  This module only detects
strong contradictions (for example an exported planning result uploaded as
current evidence).  It never infers that arbitrary content is current merely
from a filename, layer name, or business field.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from app.data.catalog.session_documents import (
    CURRENT_EVIDENCE_ROLE,
    PLANNING_BRIEF_ROLE,
    PLANNING_INSTRUCTION_ROLE,
    PLANNED_OUTPUT_ROLE,
    REFERENCE_PLAN_ROLE,
    UNCLASSIFIED_ROLE,
    document_admission_status,
    normalize_document_input_role,
    typed_source_input_role,
)


_PLANNED_MARKERS = (
    "planned",
    "planning_result",
    "planning_output",
    "planning_result",
    "planning-result",
    "plan_result",
    "planned_state",
    "planned_features",
    "selection_decision",
    "approved_execution_input",
    "execution_result",
    "spatial_changeset",
    "规划结果",
    "规划成果",
    "规划方案",
    "规划思路",
    "规划细化",
    "详细规划",
    "规划文本",
    "规划说明书",
    "产业规划",
    "规划用地",
    "规划道路",
    "规划设施",
    "目标年用地",
)

_PLANNED_HEADINGS = re.compile(
    r"^\s{0,3}#{1,6}\s*.*(?:planning[ _-]*(?:result|output)|"
    r"planned[ _-]*(?:state|features?)|selection[ _-]*decision|"
    r"execution[ _-]*result|spatial[ _-]*changeset|approved[ _-]*execution[ _-]*input|"
    r"规划结果|规划成果|规划方案|规划思路|"
    r"规划细化|详细规划|规划文本|规划说明书|产业规划|规划布局|"
    r"规划目标|目标年用地|建设项目布局)",
    re.IGNORECASE | re.MULTILINE,
)

_PLANNED_BODY_START = re.compile(
    r"^\s*(?:planning[ _-]*(?:result|output)|planned[ _-]*(?:state|features?)|"
    r"selection[ _-]*decision|execution[ _-]*result|spatial[ _-]*changeset|"
    r"approved[ _-]*execution[ _-]*input|规划结果|规划成果|规划方案|规划思路|规划细化|"
    r"详细规划|规划文本|规划说明书|最终方案|目标年规划|本次规划)",
    re.IGNORECASE,
)

_PLANNED_ARTIFACT_TERMS = re.compile(
    r"(?:planning[ _-]*(?:result|output)|plan[ _-]*result|"
    r"planned[ _-]*(?:state|features?)|selection[ _-]*decision|"
    r"approved[ _-]*execution[ _-]*input|execution[ _-]*result|"
    r"spatial[ _-]*changeset)",
    re.IGNORECASE,
)

_PLANNED_ARTIFACT_KEYS = frozenset({
    "planningresult",
    "planningoutput",
    "planresult",
    "plannedstate",
    "plannedfeature",
    "plannedfeatures",
    "selectiondecision",
    "approvedexecutioninput",
    "executionresult",
    "spatialchangeset",
    "规划结果",
    "规划成果",
    "规划方案",
    "规划思路",
    "规划细化",
    "规划用地",
    "规划道路",
    "规划设施",
    "目标年用地",
})

_OUTPUT_LINEAGE_KEYS = frozenset({
    "approval_ref",
    "candidate_id",
    "change_ref",
    "input_operation",
    "operation_parameters",
    "planned_state_ref",
    "scenario_id",
    "selection_refs",
})

_GIS_METADATA_KEYS = (
    "name", "title", "layer", "layer_name", "dataset_name",
    "layer_ref", "source_layer", "source_dataset_ref", "dataset_ref",
)

_STRONG_PLANNED_HEADING_TERMS = (
    "planning result",
    "planning output",
    "planned state",
    "planned features",
    "selection decision",
    "execution result",
    "spatial changeset",
    "approved execution input",
    "规划结果",
    "规划成果",
    "规划方案",
    "规划思路",
    "规划细化",
    "详细规划",
    "规划文本",
    "规划说明书",
    "产业规划",
    "规划布局",
    "目标年用地",
    "建设项目布局",
)


@dataclass(frozen=True)
class SourceAdmissionAssessment:
    declared_role: str
    input_role: str
    status: str
    reason: str
    signals: tuple[str, ...] = ()
    decision_basis: str = ""
    classifier_ref: str = ""
    classifier_input_digest: str = ""
    classifier_output_digest: str = ""
    classifier_model: str = ""
    classifier_confidence: float = 0.0


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def _compact_marker(value: Any) -> str:
    """Normalize separators so exported machine keys and English titles match."""

    return re.sub(r"[\s_\-./:]+", "", _normalized(value))


def _planned_tokens(value: Any, *, prefix: str) -> list[str]:
    text = _normalized(value)
    if not text:
        return []
    compact = _compact_marker(value)
    matches: list[str] = []
    for marker in _PLANNED_MARKERS:
        if marker == "planned":
            matched = re.search(
                r"(?<![a-z0-9])planned(?![a-z0-9])",
                text,
                re.IGNORECASE,
            ) is not None
        else:
            matched = _compact_marker(marker) in compact
        if matched:
            matches.append(f"{prefix}:{marker}")
    return matches


def _artifact_key_signals(
    payload: Mapping[str, Any],
    *,
    prefix: str,
) -> list[str]:
    return [
        f"{prefix}:artifact_key:{key}"
        for key in payload
        if _compact_marker(key) in _PLANNED_ARTIFACT_KEYS
    ]


def _metadata_signals(payload: Mapping[str, Any], *, prefix: str) -> list[str]:
    signals = _artifact_key_signals(payload, prefix=prefix)
    for key in _GIS_METADATA_KEYS:
        value = payload.get(key)
        signals.extend(_planned_tokens(value, prefix=f"{prefix}:{key}"))
        normalized = _normalized(value)
        if "规划" in normalized or "planned" in normalized or "planning" in normalized:
            signals.append(f"{prefix}:{key}:planned_marker")
    lineage_keys = {_normalized(key) for key in payload} & _OUTPUT_LINEAGE_KEYS
    if lineage_keys:
        signals.append("planned_lineage_keys:" + ",".join(sorted(lineage_keys)))
    return signals


def planned_output_signals(
    *,
    filename: str = "",
    parsed_text: str = "",
    gis_data: Mapping[str, Any] | None = None,
    gis_data_type: str = "",
) -> tuple[str, ...]:
    """Return bounded strong conflict signals without admitting a source."""

    signals: list[str] = []
    signals.extend(_planned_tokens(filename, prefix="filename"))
    signals.extend(_planned_tokens(gis_data_type, prefix="gis_type"))

    text = str(parsed_text or "")
    heading = _PLANNED_HEADINGS.search(text)
    if heading is not None:
        compact = " ".join(heading.group(0).split())[:120]
        signals.append(f"markdown_heading:{compact}")
    body_start = _PLANNED_BODY_START.search(text[:800])
    if body_start is not None:
        compact = " ".join(body_start.group(0).split())[:120]
        signals.append(f"body_start:{compact}")
    artifact_term = _PLANNED_ARTIFACT_TERMS.search(text)
    if artifact_term is not None:
        signals.append(
            "planned_artifact_terms:"
            + " ".join(artifact_term.group(0).split())[:120]
        )
    planning_table_terms = [
        term
        for term in ("规划项目", "建设规模", "实施时序", "投资估算", "目标年")
        if term in text
    ]
    if "规划项目" in planning_table_terms and len(planning_table_terms) >= 3:
        signals.append(
            "planned_table_columns:" + ",".join(planning_table_terms)
        )

    payload = gis_data if isinstance(gis_data, Mapping) else {}
    if payload:
        gis_filename = _normalized(filename)
        if "规划" in gis_filename or re.search(
            r"(?:^|[^a-z0-9])plann(?:ed|ing)(?:$|[^a-z0-9])",
            gis_filename,
        ):
            signals.append("gis_filename:planned_marker")
    signals.extend(_metadata_signals(payload, prefix="gis_metadata"))

    if payload.get("type") == "TableResource":
        for table_index, table in enumerate(payload.get("tables") or []):
            if not isinstance(table, Mapping):
                continue
            signals.extend(_planned_tokens(
                table.get("name"), prefix=f"table:{table_index}:name"
            ))
            signals.extend(_metadata_signals(table, prefix=f"table:{table_index}"))
            for column_index, column in enumerate(table.get("columns") or []):
                signals.extend(_planned_tokens(
                    column,
                    prefix=f"table:{table_index}:column:{column_index}",
                ))
                if _compact_marker(column) in _PLANNED_ARTIFACT_KEYS:
                    signals.append(
                        f"table:{table_index}:column:{column_index}:artifact_key:{column}"
                    )
            for row_index, row in enumerate(table.get("rows") or []):
                if not isinstance(row, Mapping):
                    continue
                signals.extend(_artifact_key_signals(
                    row, prefix=f"table:{table_index}:row:{row_index}"
                ))
                row_keys = {_normalized(key) for key in row}
                lineage_keys = row_keys & _OUTPUT_LINEAGE_KEYS
                if lineage_keys:
                    signals.append(
                        "planned_lineage_keys:" + ",".join(sorted(lineage_keys))
                    )
                for key in row:
                    signals.extend(_planned_tokens(
                        key, prefix=f"table:{table_index}:row:{row_index}:column"
                    ))

    features = payload.get("features")
    if isinstance(features, list):
        for feature_index, feature in enumerate(features):
            if not isinstance(feature, Mapping):
                continue
            signals.extend(_artifact_key_signals(
                feature, prefix=f"feature:{feature_index}"
            ))
            properties = feature.get("properties")
            if not isinstance(properties, Mapping):
                continue
            feature_metadata = dict(properties)
            if "__source_layer" in feature_metadata:
                feature_metadata["source_layer"] = feature_metadata["__source_layer"]
            signals.extend(_metadata_signals(
                feature_metadata, prefix=f"feature:{feature_index}"
            ))

    return tuple(dict.fromkeys(signals))[:16]


def has_strong_planned_output_signals(signals: tuple[str, ...] | list[str]) -> bool:
    """Return whether signals identify an artifact, not merely a task goal."""

    strong_prefixes = (
        "filename:",
        "gis_type:",
        "gis_filename:",
        "gis_metadata:",
        "feature:",
        "table:",
        "body_start:",
        "planned_artifact_terms:",
        "planned_table_columns:",
        "planned_lineage_keys:",
    )
    for raw_signal in signals:
        signal = str(raw_signal or "")
        lowered_signal = signal.casefold()
        if signal.startswith(strong_prefixes):
            return True
        if lowered_signal.startswith("markdown_heading:") and any(
            term in lowered_signal for term in _STRONG_PLANNED_HEADING_TERMS
        ):
            return True
    return False


def assess_source_admission(
    *,
    input_role: str = "",
    category: str = "",
    source: str = "",
    filename: str = "",
    parsed_text: str = "",
    gis_data: Mapping[str, Any] | None = None,
    gis_data_type: str = "",
) -> SourceAdmissionAssessment:
    """Resolve an ingress role and fail closed on a planned-output conflict."""

    signals = planned_output_signals(
        filename=filename,
        parsed_text=parsed_text,
        gis_data=gis_data,
        gis_data_type=gis_data_type,
    )
    explicit_role = normalize_document_input_role(input_role)
    typed_role = typed_source_input_role(source=source, category=category)
    declared_role = typed_role or explicit_role
    if has_strong_planned_output_signals(signals):
        return SourceAdmissionAssessment(
            declared_role=declared_role,
            input_role=PLANNED_OUTPUT_ROLE,
            status="excluded",
            reason="strong_planned_artifact_cannot_be_current_world_input",
            signals=signals,
            decision_basis="deterministic_conflict",
        )
    if explicit_role == PLANNED_OUTPUT_ROLE:
        declared_role = PLANNED_OUTPUT_ROLE
    elif typed_role and explicit_role not in {UNCLASSIFIED_ROLE, typed_role}:
        return SourceAdmissionAssessment(
            declared_role=typed_role,
            input_role=UNCLASSIFIED_ROLE,
            status="quarantined",
            reason="typed_source_conflicts_with_explicit_input_role",
            signals=signals,
            decision_basis="typed_channel_conflict",
        )
    status = document_admission_status(declared_role)
    reasons = {
        "admitted": "explicit_current_evidence_channel",
        "control_only": "planning_control_channel_not_current_fact",
        "reference_only": "reference_plan_isolated_from_current_world",
        "excluded": "planned_output_cannot_be_planning_input",
        "quarantined": "source_input_role_unclassified",
    }
    return SourceAdmissionAssessment(
        declared_role=declared_role,
        input_role=declared_role,
        status=status,
        reason=reasons[status],
        signals=signals,
        decision_basis=("typed_channel" if typed_role else "explicit_declaration"),
    )


def apply_temporal_role_decision(
    assessment: SourceAdmissionAssessment,
    decision: Any,
    *,
    enforce_positive: bool = True,
) -> SourceAdmissionAssessment:
    """Apply a verified semantic conflict decision without granting new facts."""

    selected_role = str(getattr(decision, "selected_role", "ambiguous") or "ambiguous")
    decision_status = str(getattr(decision, "status", "ambiguous") or "ambiguous")
    classifier_signals = (
        f"temporal_role:{selected_role}",
        f"temporal_status:{decision_status}",
    )
    signals = tuple(dict.fromkeys((*assessment.signals, *classifier_signals)))[:16]
    metadata = {
        "decision_basis": "llm_temporal_role_consensus",
        "classifier_ref": str(getattr(decision, "decision_ref", "") or ""),
        "classifier_input_digest": str(getattr(decision, "input_digest", "") or ""),
        "classifier_output_digest": str(getattr(decision, "raw_output_digest", "") or ""),
        "classifier_model": str(getattr(decision, "model_id", "") or ""),
        "classifier_confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
    }
    if decision_status != "accepted" or selected_role == "ambiguous":
        if (
            not enforce_positive
            and assessment.input_role == CURRENT_EVIDENCE_ROLE
            and assessment.status == "admitted"
        ):
            return SourceAdmissionAssessment(
                declared_role=assessment.declared_role,
                input_role=assessment.input_role,
                status=assessment.status,
                reason=assessment.reason,
                signals=(*signals, "temporal_role_advisory_only"),
                **{
                    **metadata,
                    "decision_basis": "explicit_typed_channel_temporal_advisory",
                },
            )
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=UNCLASSIFIED_ROLE,
            status="quarantined",
            reason=(
                "temporal_role_provider_failed"
                if decision_status == "provider_failed"
                else "temporal_role_protocol_failed"
                if decision_status == "protocol_failed"
                else "temporal_role_ambiguous"
            ),
            signals=signals,
            **metadata,
        )
    if selected_role == PLANNED_OUTPUT_ROLE:
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=PLANNED_OUTPUT_ROLE,
            status="excluded",
            reason="semantic_planned_output_cannot_be_planning_input",
            signals=signals,
            **metadata,
        )
    if selected_role == REFERENCE_PLAN_ROLE:
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=REFERENCE_PLAN_ROLE,
            status="reference_only",
            reason="semantic_reference_plan_isolated_from_current_world",
            signals=signals,
            **metadata,
        )
    if (
        selected_role == CURRENT_EVIDENCE_ROLE
        and assessment.input_role == CURRENT_EVIDENCE_ROLE
        and assessment.status == "admitted"
    ):
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=CURRENT_EVIDENCE_ROLE,
            status="admitted",
            reason="semantic_temporal_role_verified_current_evidence",
            signals=signals,
            **metadata,
        )
    if (
        selected_role == "planning_control"
        and assessment.input_role in {PLANNING_BRIEF_ROLE, PLANNING_INSTRUCTION_ROLE}
        and assessment.status == "control_only"
    ):
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=assessment.input_role,
            status="control_only",
            reason="semantic_temporal_role_verified_planning_control",
            signals=signals,
            **metadata,
        )
    return SourceAdmissionAssessment(
        declared_role=assessment.declared_role,
        input_role=UNCLASSIFIED_ROLE,
        status="quarantined",
        reason="semantic_temporal_role_conflicts_with_typed_channel",
        signals=signals,
        **metadata,
    )


async def assess_uploaded_source_admission(
    *,
    input_role: str,
    category: str,
    filename: str,
    source_digest: str = "",
    parsed_text: str = "",
    gis_data: Mapping[str, Any] | None = None,
    gis_data_type: str = "",
    parse_status: str = "success",
    temporal_llm_enabled: bool = True,
    llm: Any = None,
) -> SourceAdmissionAssessment:
    """Assess an untrusted upload and require bounded semantic consensus."""

    assessment = assess_source_admission(
        input_role=input_role,
        source="upload",
        category=category,
        filename=filename,
        parsed_text=parsed_text,
        gis_data=gis_data,
        gis_data_type=gis_data_type,
    )
    if assessment.status not in {"admitted", "control_only"}:
        return assessment
    if str(parse_status or "").casefold() != "success":
        return SourceAdmissionAssessment(
            declared_role=assessment.declared_role,
            input_role=UNCLASSIFIED_ROLE,
            status="quarantined",
            reason="source_readability_failed",
            signals=assessment.signals,
            decision_basis="parse_gate",
        )
    from app.data.ingestion.temporal_role_classifier import (
        build_temporal_role_input,
        classify_temporal_role_async,
    )

    row = build_temporal_role_input(
        source_ref=f"upload:{source_digest or filename}",
        declared_channel=assessment.input_role,
        resource_kind=str(gis_data_type or ("markdown" if parsed_text else "upload")),
        filename=filename,
        parsed_text=parsed_text,
        gis_data=gis_data,
    )
    decision = await classify_temporal_role_async(
        row,
        enabled=temporal_llm_enabled,
        llm=llm,
    )
    return apply_temporal_role_decision(
        assessment,
        decision,
        enforce_positive=assessment.input_role != CURRENT_EVIDENCE_ROLE,
    )


def is_admitted_current_assessment(
    assessment: SourceAdmissionAssessment,
) -> bool:
    return (
        assessment.input_role == CURRENT_EVIDENCE_ROLE
        and assessment.status == "admitted"
    )


__all__ = [
    "SourceAdmissionAssessment",
    "assess_source_admission",
    "assess_uploaded_source_admission",
    "apply_temporal_role_decision",
    "has_strong_planned_output_signals",
    "is_admitted_current_assessment",
    "planned_output_signals",
]
