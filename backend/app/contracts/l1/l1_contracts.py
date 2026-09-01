"""L1 stage contracts - baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.artifacts.contract_meta import ContractMeta, StageIssue
from app.contracts.evidence.evidence_contracts import (
    EvidenceGapResolution,
    EvidenceSource,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.target_projection.parse_result_contracts import ParseDiagnostic
from app.contracts.target_projection.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance


class L1SpatialProvenance(BaseModel):
    """Source lineage for one semantic-to-spatial projection."""

    source_refs: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    observation_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        for field_name in ("source_refs", "source_segment_ids"):
            if payload.get(field_name) is None:
                payload[field_name] = []
        return payload


class LocationScopeMention(BaseModel):
    """One explicitly named semantic scope around a location mention.

    Scope role is supplied by the L1 observation and never guessed from a
    name suffix.  The object is intentionally pre-geometric: it can describe
    a natural village, administrative area, place, or another named scope,
    but it cannot carry coordinates, BSMs, WKT, or a generated boundary.
    """

    name: str
    normalized_name: str = ""
    role: str = "unknown"
    relation_to_target: str = "located_in"
    aliases: list[str] = Field(default_factory=list)
    source_quote: str = ""
    source_refs: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        for field_name in ("aliases", "source_refs", "source_segment_ids"):
            if payload.get(field_name) is None:
                payload[field_name] = []
        return payload


def _legacy_scope_objects(data: Any, *, field_name: str) -> Any:
    """Translate the retired flat scope lists at the L1 boundary only."""

    if not isinstance(data, dict):
        return data
    payload = dict(data)
    if field_name in payload:
        return payload
    scopes: list[dict[str, Any]] = []
    for legacy_key, role in (
        ("village_scopes", "natural_village"),
        ("place_scopes", "place"),
    ):
        values = payload.pop(legacy_key, None) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            name = str(value or "").strip()
            if name:
                scopes.append({"name": name, "role": role})
    if scopes:
        payload[field_name] = scopes
    return payload


class LocationMentionDraft(BaseModel):
    """Provider-side semantic location draft.

    This is a transport/helper type.  It is validated inside L1 and compiled
    into :class:`LocationMention`; it is never a resolved identity or
    geometry.
    """

    mention_kind: Literal["target", "place", "anchor_request"] = "target"
    mention: str = ""
    normalized_name: str = ""
    target_name: str = ""
    role: str = "unknown"
    scope_mentions: list[LocationScopeMention] = Field(default_factory=list)
    relation: str = ""
    related_mentions: list[str] = Field(default_factory=list)
    instance_label: str = ""
    instance_count: str = ""
    resolution_state: Literal[
        "resolved",
        "needs_retrieval",
        "conflict",
        "source_exhausted",
        "unknown",
    ] = "needs_retrieval"
    aliases: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    provenance: L1SpatialProvenance = Field(default_factory=L1SpatialProvenance)

    @model_validator(mode="before")
    @classmethod
    def translate_legacy_scopes(cls, data: Any) -> Any:
        payload = _legacy_scope_objects(data, field_name="scope_mentions")
        if not isinstance(payload, dict):
            return payload
        payload = dict(payload)
        for field_name in (
            "scope_mentions",
            "aliases",
            "related_mentions",
            "source_feature_ids",
            "source_segment_ids",
            "source_refs",
        ):
            if payload.get(field_name) is None:
                payload[field_name] = []
        return payload

    @property
    def village_scopes(self) -> list[str]:
        return [
            scope.name
            for scope in self.scope_mentions
            if scope.role == "natural_village"
        ]

    @property
    def place_scopes(self) -> list[str]:
        return [
            scope.name
            for scope in self.scope_mentions
            if scope.role != "natural_village"
        ]


class LocationMention(BaseModel):
    """Traceable semantic place work item compiled by L1.

    ``target_name`` and ``scopes`` form a grounding work-item identity.  They
    do not claim that the target has already been located.  Geometry and
    canonical identity are produced only by retrieval/GROUND.
    """

    mention_kind: Literal["target", "place", "anchor_request"] = "target"
    work_item_ref: str = ""
    mention: str
    normalized_name: str
    role: str = "unknown"
    target_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    relation: str = ""
    spatial_hint: str = ""
    related_mentions: list[str] = Field(default_factory=list)
    scopes: list[LocationScopeMention] = Field(default_factory=list)
    instance_label: str = ""
    instance_count: str = ""
    resolution_state: Literal[
        "resolved",
        "needs_retrieval",
        "conflict",
        "source_exhausted",
        "unknown",
    ] = "needs_retrieval"
    provenance: L1SpatialProvenance = Field(default_factory=L1SpatialProvenance)
    source_report_ref: str = ""
    dimension_key: str = ""
    source_span: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def translate_legacy_scopes(cls, data: Any) -> Any:
        payload = _legacy_scope_objects(data, field_name="scopes")
        if not isinstance(payload, dict):
            return payload
        payload = dict(payload)
        for field_name in (
            "scopes",
            "aliases",
            "related_mentions",
            "evidence_refs",
            "evidence_artifact_refs",
            "source_feature_ids",
        ):
            if payload.get(field_name) is None:
                payload[field_name] = []
        return payload

    @property
    def village_scopes(self) -> list[str]:
        return [
            scope.name
            for scope in self.scopes
            if scope.role == "natural_village"
        ]

    @property
    def place_scopes(self) -> list[str]:
        return [
            scope.name
            for scope in self.scopes
            if scope.role != "natural_village"
        ]


class L1Fact(BaseModel):
    """Authoritative, provenance-rich fact consumed by later stages.

    ``facts`` remains a deterministic human-readable projection for old
    reports.  Retrieval, L2/L3 citation and spatial grounding should consume
    this record instead, so source kind, counting basis and source span cannot
    be lost in a display string.
    """

    fact_id: str
    statement: str
    confidence: float = 0.0
    fact_kind: Literal[
        "document_observation",
        "spatial_observation",
        "gis_observation",
        "kg_canonical_fact",
        "derived_metric",
    ]
    inference_level: Literal[
        "observed",
        "derived",
        "inferred",
        "conflicted",
        "pending",
    ] = "observed"
    uncertainty: str = ""
    status: Literal[
        "observed",
        "derived",
        "inferred",
        "conflicted",
        "pending",
    ] = "observed"
    dimension_key: str = ""
    subject_scope: str = ""
    semantic_type: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    source_refs: list[str] = Field(default_factory=list, min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source_span: str = ""
    source_snapshot_ref: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)
    derivation: str = ""


class EvidenceGap(BaseModel):
    """Structured evidence gap emitted by L1, resolvable by EXPLORE.

    ``gap_id`` links to ``EvidenceGapResolution.gap_id`` so the L1 Evidence
    Gate can track which gaps EXPLORE has resolved.
    """

    gap_id: str
    dimension: str
    description: str
    required_fact: str = ""
    severity: str = "warning"  # "info" | "warning" | "error"
    subject_ref: str = ""
    requirement_id: str = ""
    outcome_status: Literal[
        "open",
        "partial",
        "insufficient",
        "human_required",
        "failed",
        "not_available",
    ] = "open"
    reason_codes: list[str] = Field(default_factory=list)
    candidate_total: int = Field(default=0, ge=0)
    candidate_identity_total: int = Field(default=0, ge=0)
    ambiguity_status: Literal[
        "resolved",
        "multiple",
        "unresolved",
    ] = "unresolved"
    coverage_stop_reason: Literal[
        "",
        "sufficient",
        "source_exhausted",
        "human_required",
        "budget_exhausted",
    ] = ""
    evidence_artifact_ref: ArtifactRef | None = None
    allowed_sources: list[str] = Field(default_factory=list)
    retrieval_capability: str = ""
    recovery_action: str = ""
    recoverable: bool = True
    recovery_generation: int = Field(default=0, ge=0)


class L1SourceSegment(BaseModel):
    """Addressable raw-input segment exposed to the L1 extraction model.

    Segments are structural transport units only.  They deliberately do not
    assume that the source is a table, Markdown, HTML, PDF text, or a known
    ledger.  The L1 model decides what the segment means for its dimension;
    the application only preserves offsets and verifies returned evidence.
    """

    segment_id: str
    source_key: str
    source_ref: str
    content_digest: str = ""
    start_char: int = 0
    end_char: int = 0
    start_line: int = 1
    end_line: int = 1
    text: str
    section_path: list[str] = Field(default_factory=list)


class L1SourceIndex(ContractMeta):
    """Addressable source segments supplied to L1 extraction.

    This transport artifact does not interpret source material or carry a
    second asset/demand ledger. Semantic facts and their evidence references
    live only in the typed L1 observation output.
    """

    source_documents: list[str] = Field(default_factory=list)
    source_digest: str = ""
    source_segments: list[L1SourceSegment] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class L1InputContext(BaseModel):
    """Immutable identity for one L1 dimension input projection.

    The context carries only source/index identity and the dimension contract.
    It deliberately excludes raw report text, retrieved evidence, report prose,
    and mutable workflow state.  A page projection refers back to this context
    through ``input_digest``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_version: str = "l1.input.v1"
    session_id: str = ""
    dimension_key: str = Field(min_length=1)
    source_index_ref: str = ""
    source_digest: str = ""
    source_projection_digest: str = ""
    source_page_count: int = Field(default=1, ge=1)
    allowed_fact_types: tuple[str, ...] = ()
    evidence_gap_refs: tuple[str, ...] = ()
    evidence_gap_digest: str = ""
    input_digest: str = ""

    @model_validator(mode="before")
    @classmethod
    def canonicalize_digest(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        payload["allowed_fact_types"] = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (payload.get("allowed_fact_types") or ())
                if str(value).strip()
            )
        )
        payload["evidence_gap_refs"] = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (payload.get("evidence_gap_refs") or ())
                if str(value).strip()
            )
        )
        identity = {
            key: payload.get(key)
            for key in (
                "context_version",
                "session_id",
                "dimension_key",
                "source_index_ref",
                "source_digest",
                "source_projection_digest",
                "source_page_count",
                "allowed_fact_types",
                "evidence_gap_refs",
                "evidence_gap_digest",
            )
        }
        expected = "sha256:" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        provided = str(payload.get("input_digest") or "").strip()
        if provided and provided != expected:
            raise ValueError("L1 input_digest does not match the input context")
        payload["input_digest"] = expected
        return payload


class L1EvidenceGapInputRow(BaseModel):
    """Flat Evidence scheduler row exposed to one bounded L1 call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gap_ref: str = Field(min_length=1)
    subject_refs: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    status: str = "open"
    deferred_until: str = "l1"
    failure_reason: str = ""


class L1DimensionInput(BaseModel):
    """One bounded source-page projection sent to the L1 provider."""

    model_config = ConfigDict(extra="forbid")

    context: L1InputContext
    page_index: int = Field(default=0, ge=0)
    page_segment_ids: tuple[str, ...] = ()
    source_page: L1SourceIndex | None = None
    evidence_gap_rows: tuple[L1EvidenceGapInputRow, ...] = ()

    @model_validator(mode="after")
    def validate_page_projection(self) -> "L1DimensionInput":
        if self.page_index >= self.context.source_page_count:
            raise ValueError("L1 page_index is outside the input context")
        gap_payload = [
            item.model_dump(mode="json") for item in self.evidence_gap_rows
        ]
        gap_digest = "sha256:" + hashlib.sha256(
            json.dumps(
                gap_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.context.evidence_gap_digest and gap_digest != self.context.evidence_gap_digest:
            raise ValueError("L1 evidence gap rows do not match the input context")
        if tuple(item.gap_ref for item in self.evidence_gap_rows) != self.context.evidence_gap_refs:
            raise ValueError("L1 evidence gap refs do not match the input context")
        if self.source_page is None:
            if self.page_segment_ids:
                raise ValueError("L1 page_segment_ids require a source_page")
            return self
        if (
            self.context.source_digest
            and self.source_page.source_digest
            and self.context.source_digest != self.source_page.source_digest
        ):
            raise ValueError("L1 source page digest does not match the input context")
        actual_ids = tuple(
            segment.segment_id for segment in self.source_page.source_segments
        )
        if actual_ids != self.page_segment_ids:
            raise ValueError("L1 page_segment_ids do not match the source page")
        return self


class L1DimensionPassState(BaseModel):
    """Durable cursor for one bounded L1 extraction loop."""

    dimension_key: str
    source_digest: str = ""
    input_digest: str = ""
    pass_name: Literal[
        "observe",
        "report",
        "complete",
        "diagnostic",
    ] = "observe"
    attempt: int = 0
    max_attempts: int = 2
    diagnostics: list[str] = Field(default_factory=list)
    calls_used: int = 0
    max_calls: int = 4
    source_page_index: int = Field(default=0, ge=0)
    source_page_count: int = Field(default=1, ge=1)
    status: Literal["running", "complete", "diagnostic"] = "running"


class L1Snapshot(ContractMeta):
    # Authoritative typed records.  ``facts`` below is a deterministic
    # display projection generated from these records.
    fact_records: list[L1Fact] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    # Dimension-scoped facts are the auditable source for downstream strategy
    # prompts; ``facts`` remains the flattened view used by summaries.
    facts_by_dimension: dict[str, list[str]] = Field(default_factory=dict)
    location_mentions: list[LocationMention] = Field(
        default_factory=list,
        validation_alias=AliasChoices("location_mentions", "location_facts"),
    )
    constraints: list[str] = Field(default_factory=list)
    issues: list[StageIssue] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    evidence_resolutions: list[EvidenceGapResolution] = Field(
        default_factory=list
    )
    evidence_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    classification_refs: list[ClassificationRef] = Field(default_factory=list)
    dimension_provenance: list[Provenance] = Field(default_factory=list)
    spatial_facts_by_dimension: dict[str, list[str]] = Field(default_factory=dict)
    diagnostics_by_dimension: dict[str, list[ParseDiagnostic]] = Field(default_factory=dict)
    traces_by_dimension: dict[str, CompilerTrace] = Field(default_factory=dict)
    provenance: "Provenance | None" = None
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)

    @property
    def location_facts(self) -> list[LocationMention]:
        """Read-only transition view for callers not yet on the new name."""

        return self.location_mentions


# Source-compatibility names are intentionally not exported.  They allow old
# persisted fixtures to cross the boundary while all new records use the
# LocationMention contract and the new ``location_mentions`` field.
L1LocationFact = LocationMention
L1SpatialMention = LocationMentionDraft

__all__ = [
    "L1Snapshot",
    "LocationMention",
    "LocationMentionDraft",
    "LocationScopeMention",
    "L1SpatialProvenance",
    "L1Fact",
    "EvidenceGap",
    "L1SourceSegment",
    "L1SourceIndex",
    "L1InputContext",
    "L1EvidenceGapInputRow",
    "L1DimensionInput",
    "L1DimensionPassState",
]
