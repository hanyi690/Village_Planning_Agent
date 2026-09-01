"""Spatial reference contracts - closed-set spatial query DSL for PARSE.

Defines the typed contract between PARSE (NL -> spec) and KG/spatial_ops
(spec -> candidate BSM -> precise BSM). LLM produces a SpatialReferenceSpec
via instructor; KG consumes it via resolve_candidates; spatial_ops consumes
the CandidateSet for geometric refinement.

See docs/gis/integration/PARSE_SPATIAL_GROUNDING_DESIGN.md §2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.llm.closed_set_contracts import (
    CandidateDescriptor,
    ExactBatchMembershipResult,
    candidate_set_digest,
    select_closed_set_candidate,
    validate_exact_batch_membership,
)


_VALID_TOPO = ("sfTouches", "sfWithin", "sfIntersects", "sfContains", "nearby", "connected_via_road")
_VALID_TYPES = ("directional", "distance", "topological", "attributive", "composed")
_VALID_KINDS = ("entity_type", "layer_group", "place_name", "bsm", "village")
_VALID_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_VALID_OPS = ("and", "or", "not")

_SPATIAL_ROLE_ALIASES: dict[str, str] = {
    # L1 roles describe the business work item.  GROUND must translate them
    # into the small set of retrieval roles before applying source filters.
    "parent_area": "scope",
    "building_concentration_area": "scope",
    "new_building_location": "scope",
    "facility_location": "scope",
    "facility_cluster": "scope",
    "cluster_location": "scope",
    "service_area": "scope",
    "location": "scope",
    "primary_road": "road",
    "internal_road": "road",
    "east_west_road": "road",
    "parking_facility": "facility",
    "transit_facility": "facility",
    "infrastructure": "facility",
    "transportation_facility": "facility",
    "transport_facility": "facility",
    "public_facility": "facility",
    "facility_point": "facility",
    "water_body": "water",
    "water_facility": "water",
    "river": "water",
    "stream": "water",
    "road_segment": "road",
    "county_road": "road",
    "hazard_point": "hazard",
    "geological_hazard_point": "hazard",
}


def normalize_spatial_role(value: Any) -> str:
    """Normalize provider and extractor role aliases to canonical spatial roles."""

    raw = str(value or "").strip().casefold().replace("-", "_")
    raw = "_".join(raw.split())
    if not raw:
        return "unknown"
    return _SPATIAL_ROLE_ALIASES.get(raw, raw)


def render_candidate_selection_contract(candidate_ids: Iterable[str]) -> str:
    """Render the provider-facing closed-set contract for typed selection."""

    ids = tuple(dict.fromkeys(str(value).strip() for value in candidate_ids if str(value).strip()))
    allowed = json.dumps(list(ids), ensure_ascii=False)
    return "\n".join((
        "【结构化闭集候选选择契约】",
        "候选 ID 集合是输入约束，不是输出字段；不要把它复制到 JSON 中。",
        f"本次允许选择的候选 ID 集合（仅供判断）：{allowed}",
        "响应字段必须且只能是：status、selected_candidate_id、input_digest；字段以 typed schema 为准。",
        "禁止输出 allowed_candidate_ids、candidate_ids、candidates 或任何其他键。",
        "只填写声明的 typed response contract，不要输出 Markdown、解释、序号或额外字段；不要把 JSON 写入 message.content。",
        "status 只能是 selected、abstain 或 ambiguous。",
        "selected_candidate_id 必须逐字复制上面集合中的一个 ID；",
        "status 为 abstain 或 ambiguous 时 selected_candidate_id 必须是空字符串。",
        "input_digest 必须逐字复制调用方给出的 input_digest。",
        "不得创建、改写、截断或猜测候选 ID；无法确定时返回 abstain 或 ambiguous。",
        '输出形状示例（示例值不可照抄）：{"status":"abstain","selected_candidate_id":"","input_digest":"<调用方给出的值>"}',
    ))


SpatialDomainKind = Literal[
    "exact_feature",
    "parcel_extent",
    "parcel_set",
    "bbox",
    "corridor",
    "village_scope",
    "unknown",
]

QueryType = Literal[
    "directional",
    "distance",
    "topological",
    "attributive",
    "composed",
]
QueryDirection = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
QueryRelation = Literal["within", "beyond"]
QueryTopology = Literal[
    "sfTouches",
    "sfWithin",
    "sfIntersects",
    "sfContains",
    "nearby",
    "connected_via_road",
]
QueryOperator = Literal["and", "or", "not"]


class SpatialQueryDraft(BaseModel):
    """The only spatial object that an LLM is allowed to propose.

    This model contains query semantics only.  Runtime identifiers, snapshot
    lineage, source feature membership, and materialization policy are created
    by deterministic compilation from this draft.
    """

    model_config = ConfigDict(extra="forbid")

    type: QueryType
    reference: Optional[RefObject] = None
    direction: Optional[QueryDirection] = None
    relation: Optional[QueryRelation] = None
    distance_m: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    topo: Optional[QueryTopology] = None
    attr_filter: Optional[Dict[str, Any]] = None
    semantic_terms: list[str] = Field(default_factory=list, max_length=8)
    retrieval_scopes: list[
        Literal["facilities", "hazards", "roads", "waters", "parcels", "zones"]
    ] = Field(default_factory=list, max_length=6)
    op: Optional[QueryOperator] = None
    children: list["SpatialQueryDraft"] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def reject_runtime_filter_fields(self) -> "SpatialQueryDraft":
        runtime_tokens = (
            "bsm",
            "geometry",
            "coordinate",
            "wkt",
            "snapshot",
            "source_feature",
            "materialization",
            "target_id",
            "candidate",
        )
        filter_items = list((self.reference.filter if self.reference else {}).items())
        filter_items.extend(list((self.attr_filter or {}).items()))
        forbidden = [
            str(key)
            for key, _ in filter_items
            if any(token in str(key).casefold() for token in runtime_tokens)
        ]
        if forbidden:
            raise ValueError(
                "query draft cannot carry runtime identity fields: "
                + ", ".join(sorted(set(forbidden)))
            )
        return self


class CandidateSelectionProposal(BaseModel):
    """Strict LLM proposal for one runtime-owned candidate set."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["selected", "abstain", "ambiguous"]
    # Keep the field required in the provider schema.  A nullable optional
    # field was omitted by the live MiniMax tool call for selected decisions,
    # making a semantically valid selection impossible to validate.  Empty
    # string is the typed representation for abstain/ambiguous.
    selected_candidate_id: str
    input_digest: str

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CandidateSelectionProposal":
        selected_id = (self.selected_candidate_id or "").strip()
        if self.status == "selected" and not selected_id:
            raise ValueError("selected status requires selected_candidate_id")
        if self.status != "selected" and selected_id:
            raise ValueError("abstain/ambiguous status cannot carry a candidate ID")
        if selected_id != (self.selected_candidate_id or ""):
            raise ValueError("selected_candidate_id must not contain surrounding whitespace")
        if not self.input_digest.strip():
            raise ValueError("input_digest is required")
        return self


class CandidateSelectionBatchDecision(CandidateSelectionProposal):
    """One decision inside a bounded batch of independent selections."""

    decision_id: str


class CandidateSelectionBatchProposal(BaseModel):
    """Strict batch envelope for several runtime-owned candidate sets."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[CandidateSelectionBatchDecision]


class GroundTargetPriorityDecision(BaseModel):
    """LLM priority advice for already admitted grounding targets."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    priority: Literal["high", "medium", "low"]
    input_digest: str
    reason: str = Field(default="", max_length=300)


class GroundTargetPriorityBatchProposal(BaseModel):
    """Strict batch envelope for bounded target-order reasoning."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[GroundTargetPriorityDecision]


def render_candidate_selection_batch_contract() -> str:
    """Render the provider-facing contract for batched closed-set choices."""

    return "\n".join((
        "【结构化闭集批量候选选择契约】",
        "每个 decision_id 都是相互独立的选择任务；候选集合只在对应任务中作为输入约束。",
        "只填写声明的 typed batch response contract，顶层字段必须且只能是 decisions；不要把 JSON 写入 message.content。",
        "decisions 必须是数组；每个数组项的键必须且只能是：decision_id、status、selected_candidate_id、input_digest。",
        "禁止在顶层或数组项输出 allowed_candidate_ids、candidate_ids、candidates 或任何其他键。",
        "每个 decision_id 必须逐字复制任务输入；每个 input_digest 必须逐字复制同一任务输入。",
        "selected_candidate_id 只能逐字复制同一任务允许集合中的一个 ID；无法确定时 status=abstain 或 ambiguous，且 selected_candidate_id 为空字符串。",
        '输出形状示例（示例值不可照抄）：{"decisions":[{"decision_id":"<任务 ID>","status":"abstain","selected_candidate_id":"","input_digest":"<任务 digest>"}]}',
    ))


def render_ground_target_priority_contract(target_ids: Iterable[str]) -> str:
    """Render the closed target-set contract for priority advice."""

    ids = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in target_ids
            if str(value).strip()
        )
    )
    allowed = json.dumps(list(ids), ensure_ascii=False)
    return "\n".join((
        "【结构化 GROUND 目标优先级契约】",
        "这是处理顺序建议，不是空间解析结果；不得创建、改写或删除目标。",
        f"本次允许排序的 target_id 集合（仅供判断）：{allowed}",
        "顶层字段必须且只能是 decisions；数组项字段必须且只能是 target_id、priority、input_digest、reason。",
        "每个 target_id 必须逐字复制输入集合中的一个 ID；不要输出其他 ID。",
        "priority 只能是 high、medium、low；high 表示当前证据更可能完成闭集解析。",
        "input_digest 必须逐字复制对应目标输入的 digest；无法判断时使用 low。",
        "reason 只能说明证据充分度、候选规模、关系线索或缺口，不得声称已经生成坐标、几何或权威身份。",
        '输出形状示例（示例值不可照抄）：{"decisions":[{"target_id":"<输入 target_id>","priority":"low","input_digest":"<输入 digest>","reason":"证据仍不充分"}]}',
    ))


class SpatialCandidateDecision(BaseModel):
    """Auditable result after validating a candidate selection proposal."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    status: Literal["selected", "abstain", "ambiguous"]
    selected_candidate_id: str | None
    candidate_ids: tuple[str, ...]
    candidate_set_digest: str
    input_digest: str
    exact_membership: ExactBatchMembershipResult
    pending: bool = False
    reason: str = ""


def _candidate_value(candidate: Any, name: str, default: Any = "") -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def stable_spatial_candidate_id(candidate: Any, *, namespace: str = "candidate") -> str:
    """Return a deterministic ID from runtime identity, never from position."""

    namespace = "-".join(str(namespace).split()) or "candidate"
    explicit = str(_candidate_value(candidate, "candidate_id", "") or "").strip()
    if explicit and not any(char.isspace() for char in explicit):
        return explicit
    identity = _candidate_value(candidate, "identity", None)
    identity_fields = (
        "bundle_feature_bsm",
        "feature_bsm",
        "source_feature_id",
        "source_bsm",
        "entity_ref",
        "entity_uri",
        "geometry_ref",
    )
    for field_name in identity_fields:
        value = str(_candidate_value(candidate, field_name, "") or "").strip()
        if value and not any(char.isspace() for char in value):
            return value
        if identity is not None:
            value = str(_candidate_value(identity, field_name, "") or "").strip()
            if value and not any(char.isspace() for char in value):
                return value
    for field_name in ("entity_refs", "source_bsms", "related_parcel_bsms"):
        values = [
            str(value).strip()
            for value in (_candidate_value(candidate, field_name, None) or [])
            if str(value).strip()
            and not any(char.isspace() for char in str(value).strip())
        ]
        if values:
            return f"{namespace}:{values[0]}"
    payload = {
        "kind": namespace,
        "label": str(
            _candidate_value(candidate, "canonical_name", "")
            or _candidate_value(candidate, "current_name", "")
            or ""
        ).strip(),
        "entity_type": str(_candidate_value(candidate, "entity_type", "") or "").strip(),
        "role": str(_candidate_value(candidate, "role", "") or "").strip(),
        "identity": {
            field_name: _candidate_value(identity, field_name, "")
            if identity is not None
            else _candidate_value(candidate, field_name, "")
            for field_name in identity_fields
        },
        "candidate_identity": {
            field_name: _candidate_value(candidate, field_name, "")
            for field_name in identity_fields
        },
        "identity_label": str(
            _candidate_value(identity, "canonical_name", "") or ""
        ).strip(),
        "identity_entity_type": str(
            _candidate_value(identity, "entity_type", "") or ""
        ).strip(),
        "identity_role": str(_candidate_value(identity, "role", "") or "").strip(),
        "entity_refs": list(_candidate_value(candidate, "entity_refs", None) or []),
        "source_bsms": list(_candidate_value(candidate, "source_bsms", None) or []),
        "related_parcel_bsms": list(
            _candidate_value(candidate, "related_parcel_bsms", None) or []
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{namespace}:sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def spatial_candidate_descriptor(candidate: Any, *, kind: str) -> CandidateDescriptor:
    """Build a stable descriptor from runtime-owned candidate metadata."""

    identity = _candidate_value(candidate, "identity", None)
    label = str(
        _candidate_value(candidate, "canonical_name", "")
        or _candidate_value(candidate, "current_name", "")
        or _candidate_value(identity, "canonical_name", "")
        or ""
    ).strip()
    metadata = {
        "entity_type": str(
            _candidate_value(candidate, "entity_type", "")
            or _candidate_value(identity, "entity_type", "")
            or ""
        ).strip(),
        "role": str(
            _candidate_value(candidate, "role", "")
            or _candidate_value(identity, "role", "")
            or ""
        ).strip(),
        "source_feature_id": str(
            _candidate_value(candidate, "source_feature_id", "")
            or _candidate_value(identity, "source_feature_id", "")
            or ""
        ).strip(),
        "bundle_feature_bsm": str(
            _candidate_value(candidate, "feature_bsm", "")
            or _candidate_value(identity, "bundle_feature_bsm", "")
            or ""
        ).strip(),
        "source_layer": str(
            _candidate_value(candidate, "source_layer", "")
            or _candidate_value(identity, "source_layer", "")
            or ""
        ).strip(),
        "bundle_snapshot_digest": str(
            _candidate_value(candidate, "bundle_snapshot_digest", "")
            or _candidate_value(identity, "bundle_snapshot_digest", "")
            or ""
        ).strip(),
        "geometry_digest": str(
            _candidate_value(candidate, "geometry_digest", "")
            or _candidate_value(identity, "geometry_digest", "")
            or ""
        ).strip(),
    }
    return CandidateDescriptor(
        candidate_id=stable_spatial_candidate_id(candidate, namespace=kind),
        kind=kind,
        label=label,
        metadata=metadata,
    )


def spatial_candidate_input_digest(
    *,
    decision_id: str,
    query_text: str,
    candidates: Iterable[CandidateDescriptor],
) -> str:
    """Digest the semantic input and the complete runtime candidate set."""

    descriptors = list(candidates)
    payload = {
        "decision_id": str(decision_id),
        "query_text": str(query_text or ""),
        "candidate_set_digest": candidate_set_digest(descriptors),
        "candidate_ids": sorted(item.candidate_id for item in descriptors),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_spatial_candidate_proposal(
    *,
    decision_id: str,
    query_text: str,
    candidates: Iterable[CandidateDescriptor],
    proposal: CandidateSelectionProposal | Any,
) -> SpatialCandidateDecision:
    """Validate status, exact candidate membership, ID, and input digest."""

    descriptors = tuple(candidates)
    candidate_ids = tuple(item.candidate_id for item in descriptors)
    membership = validate_exact_batch_membership(candidate_ids, candidate_ids)
    set_digest = candidate_set_digest(descriptors)
    input_digest = spatial_candidate_input_digest(
        decision_id=decision_id,
        query_text=query_text,
        candidates=descriptors,
    )
    try:
        typed = (
            proposal
            if isinstance(proposal, CandidateSelectionProposal)
            else CandidateSelectionProposal.model_validate(proposal)
        )
    except Exception as exc:  # noqa: BLE001
        return SpatialCandidateDecision(
            decision_id=decision_id,
            status="ambiguous",
            selected_candidate_id=None,
            candidate_ids=candidate_ids,
            candidate_set_digest=set_digest,
            input_digest=input_digest,
            exact_membership=membership,
            pending=not descriptors or len(descriptors) > 1,
            reason=f"proposal schema rejected: {exc}",
        )
    if not membership.accepted:
        reason = "runtime candidate membership is not exact"
    elif typed.input_digest != input_digest:
        reason = "candidate selection input digest mismatch"
    elif typed.status == "selected" and not typed.selected_candidate_id:
        reason = "selected proposal must include a candidate ID"
    elif typed.status != "selected" and typed.selected_candidate_id:
        reason = "abstain or ambiguous proposal must not include a candidate ID"
    else:
        closed = select_closed_set_candidate(
            decision_id=decision_id,
            candidates=list(descriptors),
            proposed_candidate_id=(
                typed.selected_candidate_id if typed.status == "selected" else None
            ),
            abstain_allowed=True,
        )
        if typed.status == "selected" and closed.status != "selected":
            reason = closed.reason or "selected candidate is outside the closed set"
        elif typed.status == "ambiguous":
            return SpatialCandidateDecision(
                decision_id=decision_id,
                status="ambiguous",
                selected_candidate_id=None,
                candidate_ids=candidate_ids,
                candidate_set_digest=set_digest,
                input_digest=input_digest,
                exact_membership=membership,
                pending=True,
                reason="model marked candidate set ambiguous",
            )
        elif typed.status != closed.status:
            reason = "proposal status does not match closed-set decision"
        else:
            return SpatialCandidateDecision(
                decision_id=decision_id,
                status=closed.status,
                selected_candidate_id=closed.selected_candidate_id,
                candidate_ids=candidate_ids,
                candidate_set_digest=set_digest,
                input_digest=input_digest,
                exact_membership=membership,
                pending=(
                    not descriptors
                    or (len(descriptors) > 1 and closed.status != "selected")
                ),
                reason=closed.reason,
            )
    status = "ambiguous"
    return SpatialCandidateDecision(
        decision_id=decision_id,
        status="ambiguous",
        selected_candidate_id=None,
        candidate_ids=candidate_ids,
        candidate_set_digest=set_digest,
        input_digest=input_digest,
        exact_membership=membership,
        pending=(
            not membership.accepted
            or not descriptors
            or (len(descriptors) > 1 and status != "selected")
        ),
        reason=reason,
    )


class RefObject(BaseModel):
    """Reference object: resolves to a KG entity or layer group."""
    kind: str = Field(..., description="Closed set: " + ", ".join(_VALID_KINDS))
    filter: Optional[Dict[str, Any]] = Field(None, description="Attribute filter, e.g. {label_contains:'学校'}")

    model_config = {"extra": "forbid"}

    @field_validator("kind")
    @classmethod
    def kind_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {_VALID_KINDS}, got '{v}'")
        return v


class SpatialReferenceSpec(BaseModel):
    """PARSE-produced spatial reference specification. Closed-set, LLM-filled."""
    type: str = Field(..., description="Closed set: " + ", ".join(_VALID_TYPES))
    reference: Optional[RefObject] = None
    direction: Optional[str] = Field(None, description="8-wind: " + ", ".join(_VALID_DIRECTIONS))
    relation: Optional[str] = Field(None, description="within | beyond (for distance type)")
    distance_m: Optional[float] = None
    topo: Optional[str] = Field(None, description="GeoSPARQL/pln relation: " + ", ".join(_VALID_TOPO))
    attr_filter: Optional[Dict[str, Any]] = None
    semantic_terms: list[str] = Field(default_factory=list, max_length=8)
    retrieval_scopes: list[
        Literal["facilities", "hazards", "roads", "waters", "parcels", "zones"]
    ] = Field(default_factory=list, max_length=6)
    op: Optional[str] = Field(None, description="and | or | not (for composed type)")
    children: List["SpatialReferenceSpec"] = Field(default_factory=list)
    intervention_id: Optional[str] = None
    target_id: str = ""
    spec_id: str = ""
    project_ref: Optional[str] = None
    physical_project_ref: str = ""
    component_claim_refs: list[str] = Field(default_factory=list)
    component_fact_refs: list[str] = Field(default_factory=list)
    unresolved_reason: str = ""
    source_binding_ref: str = ""
    source_collection_key: str = ""
    source_snapshot_ref: str = ""
    source_feature_digest: str = ""
    source_snapshot_digest: str = ""
    l1_fact_refs: list[str] = Field(default_factory=list)
    # Preserve target materialization semantics across the PARSE -> GROUND
    # boundary.  Spatial resolution is geometry-only, but GROUND must not
    # turn a protection/functional overlay into a land-use assignment merely
    # because both happen to use polygon candidates.
    materialization_role: Literal[
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    ] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("topo")
    @classmethod
    def topo_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_TOPO:
            raise ValueError(f"topo must be one of {_VALID_TOPO}, got '{v}'")
        return v

    def all_retrieval_scopes(self) -> list[str]:
        """Return the closed candidate classes requested across a composed spec."""

        return list(dict.fromkeys([
            *self.retrieval_scopes,
            *(
                scope
                for child in self.children
                for scope in child.all_retrieval_scopes()
            ),
        ]))


def compile_spatial_query_draft(
    draft: SpatialQueryDraft,
    *,
    spec_id: str,
    target_id: str,
    source_snapshot_ref: str,
    source_snapshot_digest: str,
    materialization_role: str | None = None,
    intervention_id: str | None = None,
    project_ref: str | None = None,
    physical_project_ref: str = "",
    component_claim_refs: Iterable[str] = (),
    component_fact_refs: Iterable[str] = (),
    l1_fact_refs: Iterable[str] = (),
) -> SpatialReferenceSpec:
    """Compile semantic query input into a deterministic runtime reference.

    The caller supplies every runtime identity and lineage field.  None of
    these fields are accepted by :class:`SpatialQueryDraft`, so an LLM cannot
    manufacture snapshot, feature, or materialization provenance.
    """

    if not str(spec_id).strip() or not str(target_id).strip():
        raise ValueError("spec_id and target_id are required runtime identifiers")
    if not str(source_snapshot_ref).strip() or not str(source_snapshot_digest).strip():
        raise ValueError("source snapshot reference and digest are required")
    return SpatialReferenceSpec(
        **draft.model_dump(mode="python"),
        spec_id=str(spec_id).strip(),
        target_id=str(target_id).strip(),
        source_snapshot_ref=str(source_snapshot_ref).strip(),
        source_snapshot_digest=str(source_snapshot_digest).strip(),
        materialization_role=materialization_role,
        intervention_id=intervention_id,
        project_ref=project_ref,
        physical_project_ref=physical_project_ref,
        component_claim_refs=list(component_claim_refs),
        component_fact_refs=list(component_fact_refs),
        l1_fact_refs=list(l1_fact_refs),
    )


class GeometryRef(BaseModel):
    """Explicit source-backed geometry reference.

    A target may be backed by more than one source feature (for example a
    retained set of bus stops or a set of existing road segments).  Each
    member stays separate here; callers must not union the records into an
    executable geometry. ``source_ref`` is the stable feature/entity lineage;
    ``resource_ref`` and ``representation_ref`` identify DATA-owned resources,
    while ``source_bsms`` is optional parcel evidence associated with that
    feature.
    """
    wkt: str = ""
    crs: str = ""
    source_crs: str = ""
    normalized_crs: str = ""
    source_snapshot_ref: str = ""
    content_digest: str = ""
    bbox: tuple[float, float, float, float] | None = None
    source_feature_id: str = ""
    entity_ref: str = ""
    entity_refs: list[str] = Field(default_factory=list)
    part_ref: str = ""
    part_refs: list[str] = Field(default_factory=list)
    representation_ref: str = ""
    resource_ref: str = ""
    l1_fact_refs: list[str] = Field(default_factory=list)
    source_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    feature_bsms: list[str] = Field(default_factory=list)
    source_bsms: list[str] = Field(default_factory=list)
    feature_kind: str = ""

    model_config = {"extra": "forbid"}

    @field_validator(
        "source_refs",
        "feature_bsms",
        "source_bsms",
        "entity_refs",
        "part_refs",
    )
    @classmethod
    def _clean_refs(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


class SearchScopeRef(BaseModel):
    """Coarse retrieval scope that must not be materialized as a candidate."""

    scope_bsms: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    scope_type: SpatialDomainKind = "unknown"
    source: str = ""
    reason: str = ""
    candidate_materialization_allowed: Literal[False] = False
    provenance_refs: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    source_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    diagnostics: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("scope_bsms", "provenance_refs", "missing_requirements")
    @classmethod
    def _clean_scope_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


@dataclass
class CandidateSet:
    """KG-side candidate BSM set returned by resolve_candidates."""
    bsms: List[str] = field(default_factory=list)
    ref_bsms: List[str] = field(default_factory=list)
    # Source-backed geometries are deliberately a list of independent
    # records so a multi-feature reference cannot be collapsed to one WKT.
    ref_geometries: List[GeometryRef] = field(default_factory=list)


@dataclass
class ResolvedSpatialRef:
    """spatial_ops-side resolved spatial reference (final precise BSMs)."""
    final_bsms: List[str] = field(default_factory=list)
    bbox: Optional[List[float]] = None
    reference_geometry_wkt: Optional[str] = None
    reference_geometries: List[GeometryRef] = field(default_factory=list)
    search_scope: SearchScopeRef | None = None
    spatial_domain_kind: SpatialDomainKind = "unknown"
    confidence: float = 0.0
    uncertainty_radius_m: float = 0.0
    uncertainty_reason: str = ""
    feature_bsms: List[str] = field(default_factory=list)
    source_feature_ids: List[str] = field(default_factory=list)
    entity_refs: List[str] = field(default_factory=list)
    part_refs: List[str] = field(default_factory=list)
    relation_refs: List[str] = field(default_factory=list)
    l1_fact_refs: List[str] = field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    source_collection_key: str = ""
    source_snapshot_ref: str = ""
    source_feature_digest: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)


SpatialQueryDraft.model_rebuild()


__all__ = [
    "RefObject",
    "SpatialQueryDraft",
    "SpatialReferenceSpec",
    "compile_spatial_query_draft",
    "CandidateSelectionProposal",
    "SpatialCandidateDecision",
    "stable_spatial_candidate_id",
    "spatial_candidate_descriptor",
    "spatial_candidate_input_digest",
    "validate_spatial_candidate_proposal",
    "GeometryRef",
    "SearchScopeRef",
    "CandidateSet",
    "ResolvedSpatialRef",
    "SpatialDomainKind",
]
