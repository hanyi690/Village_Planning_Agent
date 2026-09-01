"""Provider-facing and internal L1 planning fact contracts.

The internal observe result is a discriminated union.  The provider wire
result is deliberately flatter: it carries a stable fact_type and optional
semantic fields, while branch requirements and dimension membership are
validated locally.  Spatial locators are coarse evidence hints; no
coordinates or geometry are accepted at L1.
"""

from __future__ import annotations

import hashlib
import re
import json
import unicodedata
from functools import lru_cache
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    create_model,
    field_validator,
    model_validator,
)

from app.contracts.json_container import decode_json_container
from app.contracts.l1.l1_contracts import (
    L1DimensionPassState,
    L1InputContext,
    LocationMentionDraft,
)
from app.modules.l1.spatial_admission import (
    evaluate_location_name,
    evaluate_spatial_entity,
)


_MAX_PROVIDER_REFS = 12
_MAX_PROVIDER_OBSERVATIONS = 16


class L1SourceEvidence(BaseModel):
    """Evidence lineage shared by every L1 planning fact."""

    model_config = ConfigDict(extra="forbid")

    semantic_type: str = ""
    description: str = ""
    target_name: str = ""
    aliases: list[str] = Field(default_factory=list, max_length=8)
    spatial_mentions: list[LocationMentionDraft] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Explicit semantic place/object work items from this source row; "
            "no coordinates, geometry, BSM, canonical entity IDs or candidates."
        ),
    )
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    related_observation_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)
    constraint_refs: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)
    source_feature_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)
    source_segment_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)
    source_quote: str = ""
    source_refs: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)
    confidence: float | None = None
    status: Literal["confirmed", "uncertain", "conflict", "source_exhausted"]

    @field_validator("attributes", mode="before")
    @classmethod
    def normalize_attribute_scalars(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[str(key)] = (
                str(item) if isinstance(item, (str, int, float, bool)) else item
            )
        return normalized


def _require_non_blank(value: str) -> str:
    """Reject an admitted semantic field that has no usable value."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("semantic field must not be blank")
    return normalized


class L1SpatialLocator(BaseModel):
    """Coarse spatial evidence, never a coordinate or geometry."""

    model_config = ConfigDict(extra="forbid")

    place_names: list[str] = Field(default_factory=list, max_length=8)
    relation: str = ""
    source_feature_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROVIDER_REFS)


class L1SpatialEntityFact(L1SourceEvidence):
    fact_type: Literal["spatial_entity"]
    entity_type: str
    name: str
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)
    scale: str = ""

    _validate_required_semantics = field_validator("entity_type", "name")(
        _require_non_blank
    )

    @model_validator(mode="after")
    def validate_spatial_semantics(self) -> "L1SpatialEntityFact":
        decision = evaluate_spatial_entity(self)
        if not decision.admitted:
            raise ValueError(
                f"l1_spatial_entity_not_admissible:{decision.reason_code}"
            )
        return self


class L1SpatialRelationFact(L1SourceEvidence):
    fact_type: Literal["spatial_relation"]
    subject_ref: str
    predicate: str
    object_ref: str

    _validate_required_semantics = field_validator(
        "subject_ref", "predicate", "object_ref"
    )(_require_non_blank)

    @model_validator(mode="after")
    def validate_spatial_relation_terms(self) -> "L1SpatialRelationFact":
        for field_name, value in (
            ("subject_ref", self.subject_ref),
            ("object_ref", self.object_ref),
        ):
            decision = evaluate_location_name(
                value,
                relation=self.predicate,
                source_feature_ids=self.source_feature_ids,
                source_quote=self.source_quote,
            )
            if not decision.admitted:
                raise ValueError(
                    "l1_spatial_relation_term_not_admissible:"
                    f"{field_name}:{decision.reason_code}"
                )
        return self


class L1ScopedMetricFact(L1SourceEvidence):
    fact_type: Literal["scoped_metric"]
    metric: str
    scope: str

    _validate_required_semantics = field_validator("metric", "scope")(
        _require_non_blank
    )


class L1DemandFact(L1SourceEvidence):
    fact_type: Literal["demand"]
    demand_type: str
    scope: str
    beneficiary: str = ""
    spatial_requirement: Literal["none", "place_binding", "demand_points"] = "none"
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)

    _validate_required_semantics = field_validator("demand_type", "scope")(
        _require_non_blank
    )


class L1ConstraintFact(L1SourceEvidence):
    fact_type: Literal["constraint"]
    constraint_type: str
    applies_to_scope: str
    strength: Literal["hard", "soft", "unknown"] = "unknown"
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)

    _validate_required_semantics = field_validator(
        "constraint_type", "applies_to_scope"
    )(_require_non_blank)


class L1RiskOpportunityFact(L1SourceEvidence):
    fact_type: Literal["risk", "opportunity"]
    subject: str
    scope: str
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)

    _validate_required_semantics = field_validator("subject", "scope")(
        _require_non_blank
    )


class L1RiskFact(L1RiskOpportunityFact):
    fact_type: Literal["risk"]


class L1OpportunityFact(L1RiskOpportunityFact):
    fact_type: Literal["opportunity"]


class L1DocumentObservationFact(L1SourceEvidence):
    fact_type: Literal["document_observation"]
    subject: str
    scope: str

    _validate_required_semantics = field_validator("subject", "scope")(
        _require_non_blank
    )


L1PlanningFactDraft = Annotated[
    Union[
        L1SpatialEntityFact,
        L1SpatialRelationFact,
        L1ScopedMetricFact,
        L1DemandFact,
        L1ConstraintFact,
        L1RiskFact,
        L1OpportunityFact,
        L1DocumentObservationFact,
    ],
    Field(discriminator="fact_type"),
]

_FACT_ADAPTER = TypeAdapter(L1PlanningFactDraft)


_FACT_TYPE_MODELS: dict[str, type[L1SourceEvidence]] = {
    "spatial_entity": L1SpatialEntityFact,
    "spatial_relation": L1SpatialRelationFact,
    "scoped_metric": L1ScopedMetricFact,
    "demand": L1DemandFact,
    "constraint": L1ConstraintFact,
    "risk": L1RiskFact,
    "opportunity": L1OpportunityFact,
    "document_observation": L1DocumentObservationFact,
}


def _normalize_fact_type_names(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip())
    )


@lru_cache(maxsize=None)
def _fact_adapter_for_allowed_fact_types(
    allowed_fact_types: tuple[str, ...],
) -> TypeAdapter[Any]:
    normalized = _normalize_fact_type_names(allowed_fact_types)
    if not normalized:
        return _FACT_ADAPTER
    selected = tuple(_FACT_TYPE_MODELS.get(value) for value in normalized)
    if any(model is None for model in selected):
        unknown = [value for value, model in zip(normalized, selected) if model is None]
        raise ValueError(f"unknown L1 fact_type(s): {unknown}")
    selected_models = tuple(model for model in selected if model is not None)
    all_models = tuple(dict.fromkeys(_FACT_TYPE_MODELS.values()))
    if set(selected_models) == set(all_models):
        return _FACT_ADAPTER
    union_type = Union.__getitem__(selected_models)
    fact_type_union = Annotated[union_type, Field(discriminator="fact_type")]
    return TypeAdapter(fact_type_union)


def _decode_json_container(value: str) -> Any:
    """Decode a provider JSON container without accepting executable text."""
    return decode_json_container(value)


def _normalize_sequence_container(
    value: Any,
    *,
    field_name: str,
) -> list[Any]:
    """Accept common provider list containers at the typed boundary."""

    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = _decode_json_container(candidate)
        except ValueError as exc:
            # Some non-strict providers serialize the observations array and
            # then append the sibling envelope field inside the same string:
            # ``[...], "diagnostics": []}``.  Recover the complete array only
            # when the suffix is a valid diagnostics-only envelope tail.  No
            # arbitrary suffix or partial array is accepted.
            if field_name != "observations":
                raise
            stripped = candidate.strip()
            try:
                decoded, end = json.JSONDecoder().raw_decode(stripped)
                suffix = stripped[end:].strip()
                if not isinstance(decoded, list) or not suffix.startswith(","):
                    raise ValueError
                tail = json.loads("{" + suffix[1:])
                if (
                    not isinstance(tail, dict)
                    or set(tail) != {"diagnostics"}
                    or not isinstance(tail["diagnostics"], list)
                ):
                    raise ValueError
                candidate = decoded
            except (TypeError, ValueError, json.JSONDecodeError):
                raise exc
    while isinstance(candidate, dict):
        for key in (field_name, "items", "records", "values"):
            nested = candidate.get(key)
            if nested is not None:
                candidate = nested
                break
        else:
            break
        if isinstance(candidate, str):
            candidate = _decode_json_container(candidate)
    if not isinstance(candidate, list):
        raise TypeError(f"{field_name} must decode to a list")
    return candidate


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    candidate = value
    if isinstance(candidate, str):
        candidate = _decode_json_container(candidate)
    if not isinstance(candidate, list):
        raise TypeError(f"{field_name} must decode to a list")
    return [str(item).strip() for item in candidate if str(item).strip()]


def _safe_payload_copy(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            sanitized[str(key)[:120]] = _safe_payload_copy(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_safe_payload_copy(item) for item in list(value)[:64]]
    return str(value)[:2000]


def _payload_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _safe_payload_copy(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _error_paths(exc: Exception) -> list[str]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return ["<model>"]
    try:
        rows = errors()
    except Exception:
        return ["<model>"]
    paths: list[str] = []
    for row in rows:
        loc = row.get("loc") or ()
        if not isinstance(loc, (list, tuple)) or not loc:
            paths.append("<model>")
            continue
        parts: list[str] = []
        for token in loc:
            if isinstance(token, int):
                if parts:
                    parts[-1] = f"{parts[-1]}[{token}]"
                else:
                    parts.append(f"[{token}]")
            else:
                parts.append(str(token))
        paths.append(".".join(part for part in parts if part) or "<model>")
    return list(dict.fromkeys(paths or ["<model>"]))


def _quarantine_error_paths(item: Any, exc: Exception) -> list[str]:
    if isinstance(item, dict) and not str(item.get("fact_type") or "").strip():
        return ["fact_type", "<union_discriminator>"]
    raw_paths = _error_paths(exc)
    leaf_paths = [
        path.rsplit(".", 1)[-1].rsplit("[", 1)[0]
        for path in raw_paths
        if path not in {"<model>", "<union_discriminator>"}
    ]
    return list(dict.fromkeys([*raw_paths, *[path for path in leaf_paths if path]]))


def _quarantine_reason_codes(exc: Exception) -> list[str]:
    """Recover stable local-admission codes without serializing provider prose."""

    reasons: list[str] = []
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            rows = errors()
        except Exception:
            rows = []
        for row in rows:
            message = str(row.get("msg") or "")
            reasons.extend(
                re.findall(
                    r"l1_(?:spatial_entity|spatial_relation_term)_not_admissible:"
                    r"[a-z0-9_:-]+",
                    message,
                )
            )
    return list(dict.fromkeys(reasons))


@lru_cache(maxsize=None)
def build_l1_observation_output_model(
    allowed_fact_types: tuple[str, ...],
    *,
    required_fact_types: tuple[str, ...] = (),
) -> type["L1ObservationPassOutput"]:
    """Build the smallest strict internal observe model for one dimension.

    The provider uses the stable flat wire model above.  This local model
    narrows the internal discriminated union to the dimension contract after
    the provider response has crossed the wire boundary.
    """

    normalized = _normalize_fact_type_names(allowed_fact_types)
    if not normalized:
        raise ValueError("at least one L1 fact_type is required")
    unknown = [value for value in normalized if value not in _FACT_TYPE_MODELS]
    if unknown:
        raise ValueError(f"unknown L1 fact_type(s): {unknown}")
    selected_models = tuple(_FACT_TYPE_MODELS[value] for value in normalized)
    required = tuple(
        value for value in _normalize_fact_type_names(required_fact_types) if value in normalized
    )
    suffix = "_" + "_".join(normalized)
    if required:
        suffix += "_required_" + "_".join(required)

    union_type = Union.__getitem__(selected_models)
    fact_type_union = Annotated[union_type, Field(discriminator="fact_type")]
    model_name = f"L1ObservationPassOutput{suffix}"
    return create_model(
        model_name,
        __base__=L1ObservationPassOutput,
        __module__=__name__,
        observations=(list[fact_type_union], Field(default_factory=list)),
        provisional_fact_records=(list[fact_type_union], Field(default_factory=list)),
        allowed_fact_types=(tuple[str, ...], Field(default=normalized, frozen=True)),
        required_fact_types=(tuple[str, ...], Field(default=required, frozen=True)),
    )


class L1ProviderSourceEvidence(BaseModel):
    """Flat provider wire evidence with strict field admission."""

    model_config = ConfigDict(extra="forbid")

    semantic_type: str | None = None
    description: str | None = None
    target_name: str | None = None
    aliases: list[str] | None = None
    place_names: list[str] = Field(default_factory=list, max_length=8)
    location_relation: str = ""
    location_role: str = "unknown"
    location_source_feature_ids: list[str] = Field(
        default_factory=list,
        max_length=_MAX_PROVIDER_REFS,
    )
    value: str | int | float | bool | None = None
    unit: str | None = None
    counting_basis: str | None = None
    related_observation_ids: list[str] | None = None
    constraint_refs: list[str] | None = None
    source_feature_ids: list[str] | None = None
    # The wire envelope must also represent an explicit uncertain observation
    # when the current source page contains no supporting span.  The local
    # source validator quarantines such an item before it becomes a fact.
    source_segment_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    source_refs: list[str] | None = None
    confidence: float | None = None
    status: str = "uncertain"

    @model_validator(mode="before")
    @classmethod
    def decode_transport_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        for field_name in (
            "aliases",
            "related_observation_ids",
            "constraint_refs",
            "source_feature_ids",
            "place_names",
            "location_source_feature_ids",
            "source_segment_ids",
            "source_refs",
        ):
            if field_name in payload and isinstance(payload[field_name], str):
                payload[field_name] = _decode_json_container(payload[field_name])
            if payload.get(field_name) is None:
                payload[field_name] = []
        return payload


class L1ProviderObservation(L1ProviderSourceEvidence):
    """Flat provider wire item; strict variant validation stays local."""

    # Keep malformed rows representable so the application can quarantine one
    # row without discarding the complete provider envelope.  The conditional
    # schema still tells the provider which branch fields are required when a
    # known fact_type is selected; a missing/unknown fact_type remains an
    # auditable row-level quarantine case.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {
                            "fact_type": {"const": "spatial_entity"}
                        }
                    },
                    "then": {"required": ["entity_type", "name"]},
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {
                            "fact_type": {"const": "spatial_relation"}
                        }
                    },
                    "then": {
                        "required": ["subject_ref", "predicate", "object_ref"]
                    },
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {
                            "fact_type": {"const": "scoped_metric"}
                        }
                    },
                    "then": {"required": ["metric", "scope"]},
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {"fact_type": {"const": "demand"}}
                    },
                    "then": {"required": ["demand_type", "scope"]},
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {"fact_type": {"const": "constraint"}}
                    },
                    "then": {
                        "required": ["constraint_type", "applies_to_scope"]
                    },
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {
                            "fact_type": {"enum": ["risk", "opportunity"]}
                        }
                    },
                    "then": {"required": ["subject", "scope"]},
                },
                {
                    "if": {
                        "required": ["fact_type"],
                        "properties": {
                            "fact_type": {"const": "document_observation"}
                        }
                    },
                    "then": {"required": ["subject", "scope"]},
                },
            ]
        },
    )

    # Keep this field optional only at the provider wire boundary.  A missing
    # discriminator is retained long enough for the internal projector to
    # quarantine that one row; it must never be inferred from prose or from a
    # neighbouring field.  The internal discriminated union remains strict.
    fact_type: str | None = Field(
        default=None,
        description="One of the closed L1 fact types; missing or unknown values are quarantined.",
        json_schema_extra={
            "enum": [
                "spatial_entity",
                "spatial_relation",
                "scoped_metric",
                "demand",
                "constraint",
                "risk",
                "opportunity",
                "document_observation",
                None,
            ]
        },
    )
    entity_type: str | None = Field(
        default=None,
        description=(
            "Required when fact_type=spatial_entity. Use the source-backed entity "
            "family such as settlement, road, water, or facility; never leave it "
            "blank and never derive it from an unmentioned taxonomy."
        ),
    )
    name: str | None = Field(
        default=None,
        description=(
            "Required when fact_type=spatial_entity. Copy the source-backed name "
            "or explicit label; do not use a generic placeholder."
        ),
    )
    scale: str | None = Field(
        default=None,
        description="Optional source-backed scale; do not calculate or infer it.",
    )
    subject_ref: str | None = Field(
        default=None,
        description="Required when fact_type=spatial_relation; copy the source-backed subject.",
    )
    predicate: str | None = Field(
        default=None,
        description="Required when fact_type=spatial_relation; copy the source-backed relation.",
    )
    object_ref: str | None = Field(
        default=None,
        description="Required when fact_type=spatial_relation; copy the source-backed object.",
    )
    metric: str | None = Field(
        default=None,
        description="Required when fact_type=scoped_metric; copy the metric named by the source.",
    )
    scope: str | None = Field(
        default=None,
        description=(
            "Required for scoped_metric, demand, risk, opportunity, and "
            "document_observation; copy the explicit source scope."
        ),
    )
    demand_type: str | None = Field(
        default=None,
        description="Required when fact_type=demand; copy the source-backed demand type.",
    )
    beneficiary: str | None = Field(
        default=None,
        description="Optional demand beneficiary only when explicitly stated by the source.",
    )
    spatial_requirement: str | None = Field(
        default=None,
        description="Demand spatial requirement; use none unless the source explicitly requires a place or demand point.",
    )
    constraint_type: str | None = Field(
        default=None,
        description="Required when fact_type=constraint; copy the source-backed constraint type.",
    )
    applies_to_scope: str | None = Field(
        default=None,
        description="Required when fact_type=constraint; copy the explicit affected scope.",
    )
    strength: str | None = Field(
        default=None,
        description="Constraint strength only when explicit; otherwise use the local unknown default.",
    )
    subject: str | None = Field(
        default=None,
        description=(
            "Required for risk, opportunity, and document_observation; copy the "
            "source-backed subject without turning a recommendation into a fact."
        ),
    )


class L1ObservationProviderOutput(BaseModel):
    """Minimal provider envelope for the L1 observe pass.

    Quarantine, provisional records, and dimension coverage are deterministic
    application state.  They are deliberately not exposed in the provider
    tool schema; otherwise the model sees an internal recovery envelope and a
    semantic output envelope as one contract.
    """

    model_config = ConfigDict(extra="forbid")

    observations: list[L1ProviderObservation] = Field(
        default_factory=list,
        max_length=_MAX_PROVIDER_OBSERVATIONS,
        description=(
            "At most 16 source-backed, planning-relevant rows from the current "
            "page. Each row "
            "must satisfy the conditional required fields described on its fact_type. "
            "Rows with missing conditional fields are rejected locally, not repaired."
        ),
    )
    diagnostics: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def decode_provider_containers(cls, data: Any) -> Any:
        """Normalize provider JSON containers before wire validation."""

        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if isinstance(payload.get("observations"), list) and any(
            not isinstance(item, dict) for item in payload["observations"]
        ):
            raise TypeError("L1 provider observation rows must be objects")
        if "observations" in payload:
            payload["observations"] = _normalize_sequence_container(
                payload.get("observations", []),
                field_name="observations",
            )
        payload["diagnostics"] = _normalize_string_list(
            payload.get("diagnostics", []),
            field_name="diagnostics",
        )
        return payload


@lru_cache(maxsize=None)
def build_l1_observation_provider_model(
    allowed_fact_types: tuple[str, ...],
) -> type[L1ObservationProviderOutput]:
    """Return the stable provider-only L1 schema with no recovery fields.

    ``allowed_fact_types`` is still validated here so a malformed dimension
    contract fails before a provider call.  It intentionally does not alter
    the provider schema: the eight semantic branches are fixed, while the
    dimension-specific allowlist is enforced by the local projection into the
    strict internal model.  This keeps the provider/tool schema identity
    stable across dimensions and leaves runtime catalogs out of ``oneOf``.
    """

    normalized = _normalize_fact_type_names(allowed_fact_types)
    if not normalized:
        raise ValueError("at least one L1 fact_type is required")
    unknown = [value for value in normalized if value not in _FACT_TYPE_MODELS]
    if unknown:
        raise ValueError(f"unknown L1 fact_type(s): {unknown}")
    del normalized
    return L1ObservationProviderOutput


def l1_observation_provider_model_for_dimension(
    dimension_key: str,
) -> type[L1ObservationProviderOutput]:
    """Return the provider-facing observe schema for one dimension."""

    from app.modules.l1.dimension_contracts import get_dimension_semantic_contract

    contract = get_dimension_semantic_contract(dimension_key, 1)
    allowed = tuple(contract.get("l1_fact_types", []) or [])
    return build_l1_observation_provider_model(allowed)


def _provider_string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _provider_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    candidate = value
    if isinstance(candidate, str):
        candidate = _decode_json_container(candidate)
    if not isinstance(candidate, (list, tuple, set)):
        raise TypeError("provider list field must decode to a list")
    return [item for raw in candidate if (item := _provider_string(raw))]


_PROVIDER_STATUS_ALIASES = {
    "confirmed": "confirmed",
    "verified": "confirmed",
    "supported": "confirmed",
    "已验证": "confirmed",
    "uncertain": "uncertain",
    "observed": "uncertain",
    "inferred": "uncertain",
    "likely": "uncertain",
    "possible": "uncertain",
    "待核验": "uncertain",
    "conflict": "conflict",
    "ambiguous": "conflict",
    "rejected": "conflict",
    "矛盾": "conflict",
    "source_exhausted": "source_exhausted",
    "exhausted": "source_exhausted",
    "not_found": "source_exhausted",
    "来源不足": "source_exhausted",
}

# These are transport aliases only.  They do not decide whether a constraint
# is hard or whether a demand needs a spatial binding; they only admit a
# provider's unambiguous spelling into the closed local enum.  Unknown values
# stay untouched and are quarantined by the strict internal model.
_PROVIDER_DEMAND_SPATIAL_REQUIREMENT_ALIASES = {
    "none": "none",
    "none_required": "none",
    "not_spatial": "none",
    "non_spatial": "none",
    "no_spatial_requirement": "none",
    "无": "none",
    "无空间要求": "none",
    "place": "place_binding",
    "place_name": "place_binding",
    "place_binding": "place_binding",
    "spatial": "place_binding",
    "spatial_binding": "place_binding",
    "location": "place_binding",
    "location_binding": "place_binding",
    "地点": "place_binding",
    "位置": "place_binding",
    "demand_point": "demand_points",
    "demand_points": "demand_points",
    "point": "demand_points",
    "points": "demand_points",
    "spatial_points": "demand_points",
    "需求点": "demand_points",
}

_PROVIDER_CONSTRAINT_STRENGTH_ALIASES = {
    "hard": "hard",
    "hard_constraint": "hard",
    "mandatory": "hard",
    "mandatory_constraint": "hard",
    "strict": "hard",
    "法定": "hard",
    "法定要求": "hard",
    "强制": "hard",
    "强制约束": "hard",
    "soft": "soft",
    "soft_constraint": "soft",
    "advisory": "soft",
    "recommended": "soft",
    "recommendation": "soft",
    "指导性": "soft",
    "建议": "soft",
    "unknown": "unknown",
    "unspecified": "unknown",
    "not_stated": "unknown",
    "unclear": "unknown",
    "未知": "unknown",
    "未说明": "unknown",
}


def _provider_enum_token(value: Any) -> str:
    """Normalize enum spelling without changing its semantic value."""

    token = unicodedata.normalize("NFKC", str(value or "").strip()).casefold()
    return re.sub(r"[\s\-/]+", "_", token)


def _normalize_provider_enum(
    value: Any,
    *,
    aliases: dict[str, str],
    field_name: str,
    ordinal: int,
    diagnostics: list[str],
) -> Any:
    if value is None:
        return value
    raw = _provider_string(value)
    if not raw:
        return raw
    normalized = aliases.get(_provider_enum_token(raw))
    if normalized is None:
        return raw
    if normalized != raw:
        diagnostics.append(
            f"l1_provider_enum_normalized:{ordinal}:{field_name}:{raw}->{normalized}"
        )
    return normalized

def _normalize_provider_observation(
    raw: Any,
    *,
    ordinal: int,
    diagnostics: list[str],
) -> Any:
    if not isinstance(raw, dict):
        return raw
    payload = dict(raw)
    for field_name in (
        "semantic_type",
        "description",
        "target_name",
        "source_quote",
        "location_relation",
        "location_role",
    ):
        payload[field_name] = _provider_string(payload.get(field_name))
    for field_name in (
        "aliases",
        "related_observation_ids",
        "constraint_refs",
        "source_feature_ids",
        "place_names",
        "location_source_feature_ids",
        "source_segment_ids",
        "source_refs",
    ):
        payload[field_name] = _provider_string_list(payload.get(field_name))
    payload["unit"] = _provider_string(payload.get("unit"))
    payload["counting_basis"] = _provider_string(payload.get("counting_basis"))
    raw_status = _provider_string(payload.get("status"))
    normalized_status = raw_status.casefold().replace("-", "_").replace(" ", "_")
    status = _PROVIDER_STATUS_ALIASES.get(normalized_status)
    if not raw_status:
        status = "uncertain"
        diagnostics.append(f"l1_provider_status_defaulted:{ordinal}:uncertain")
    elif status is None:
        status = "uncertain"
        diagnostics.append(
            f"l1_provider_status_normalized:{ordinal}:{raw_status}->uncertain"
        )
    elif status != raw_status:
        diagnostics.append(
            f"l1_provider_status_normalized:{ordinal}:{raw_status}->{status}"
        )
    payload["status"] = status

    fact_type = _provider_string(payload.get("fact_type"))
    for field_name in {
        "entity_type",
        "name",
        "scale",
        "subject_ref",
        "predicate",
        "object_ref",
        "metric",
        "scope",
        "demand_type",
        "beneficiary",
        "constraint_type",
        "applies_to_scope",
        "subject",
    }:
        if field_name in payload:
            payload[field_name] = _provider_string(payload.get(field_name))
    if fact_type == "demand":
        payload["spatial_requirement"] = _normalize_provider_enum(
            payload.get("spatial_requirement"),
            aliases=_PROVIDER_DEMAND_SPATIAL_REQUIREMENT_ALIASES,
            field_name="spatial_requirement",
            ordinal=ordinal,
            diagnostics=diagnostics,
        )
    if fact_type == "constraint":
        payload["strength"] = _normalize_provider_enum(
            payload.get("strength"),
            aliases=_PROVIDER_CONSTRAINT_STRENGTH_ALIASES,
            field_name="strength",
            ordinal=ordinal,
            diagnostics=diagnostics,
        )
    if fact_type == "demand" and payload.get("spatial_requirement") is None:
        payload["spatial_requirement"] = "none"
    if fact_type == "constraint" and payload.get("strength") is None:
        payload["strength"] = "unknown"
    location_feature_ids = payload.get("location_source_feature_ids") or []
    place_names: list[str] = []
    for place_name in payload.get("place_names") or []:
        admission = evaluate_location_name(
            place_name,
            role=payload.get("location_role") or "unknown",
            relation=payload.get("location_relation") or "",
            source_feature_ids=location_feature_ids,
            source_quote=payload.get("source_quote") or "",
        )
        if admission.admitted:
            place_names.append(place_name)
            continue
        diagnostics.append(
            f"l1_location_mention_not_admissible:{ordinal}:"
            f"{admission.reason_code}:{_payload_digest(place_name)[:12]}"
        )
    payload["place_names"] = list(dict.fromkeys(place_names))
    if fact_type in {"spatial_entity", "demand", "constraint", "risk", "opportunity"}:
        payload["locator"] = {
            "place_names": place_names,
            "relation": payload.get("location_relation") or "",
            "source_feature_ids": location_feature_ids,
        }
    target_label = _provider_string(
        payload.get("target_name")
        or payload.get("name")
        or payload.get("subject")
        or payload.get("demand_type")
        or payload.get("constraint_type")
        or payload.get("subject_ref")
    )
    spatial_mentions: list[dict[str, Any]] = []
    if fact_type == "spatial_entity" and target_label:
        spatial_mentions.append({
            "mention_kind": "target",
            "mention": target_label,
            "target_name": target_label,
            "role": payload.get("location_role") or "unknown",
            "scope_mentions": [
                {
                    "name": place_name,
                    "role": payload.get("location_role") or "unknown",
                    "relation_to_target": payload.get("location_relation") or "located_in",
                    "source_quote": payload.get("source_quote") or "",
                    "source_refs": payload.get("source_refs") or [],
                    "source_segment_ids": payload.get("source_segment_ids") or [],
                    "confidence": payload.get("confidence") or 0.0,
                }
                for place_name in place_names
            ],
            "relation": payload.get("location_relation") or "located_in",
            "resolution_state": "needs_retrieval",
            "aliases": payload.get("aliases") or [],
            "source_feature_ids": location_feature_ids,
            "provenance": {
                "source_refs": payload.get("source_refs") or [],
                "source_segment_ids": payload.get("source_segment_ids") or [],
                "source_quote": payload.get("source_quote") or "",
            },
        })
    elif fact_type == "spatial_relation":
        relation_places = list(dict.fromkeys(
            value
            for value in (
                payload.get("subject_ref"),
                payload.get("object_ref"),
            )
            if value
        ))
        for place_name in relation_places:
            is_subject = place_name == payload.get("subject_ref")
            spatial_mentions.append({
                "mention_kind": "place",
                "mention": place_name,
                "target_name": place_name,
                "role": payload.get("location_role") or "unknown",
                "scope_mentions": [],
                "relation": (
                    payload.get("location_relation") or ""
                    if is_subject else ""
                ),
                "related_mentions": [
                    value
                    for value in relation_places
                    if is_subject and value != place_name
                ],
                "resolution_state": "needs_retrieval",
                "aliases": [],
                "source_feature_ids": location_feature_ids,
                "provenance": {
                    "source_refs": payload.get("source_refs") or [],
                    "source_segment_ids": payload.get("source_segment_ids") or [],
                    "source_quote": payload.get("source_quote") or "",
                },
            })
    elif place_names and (
        fact_type in {"constraint", "risk", "opportunity"}
        or (
            fact_type == "demand"
            and payload.get("spatial_requirement") != "none"
        )
    ):
        for place_name in dict.fromkeys(place_names):
            spatial_mentions.append({
                "mention_kind": "place",
                "mention": place_name,
                "target_name": place_name,
                "role": payload.get("location_role") or "place",
                "scope_mentions": [],
                "relation": payload.get("location_relation") or "located_in",
                "resolution_state": "needs_retrieval",
                "aliases": [],
                "source_feature_ids": location_feature_ids,
                "provenance": {
                    "source_refs": payload.get("source_refs") or [],
                    "source_segment_ids": payload.get("source_segment_ids") or [],
                    "source_quote": payload.get("source_quote") or "",
                },
            })
    payload["spatial_mentions"] = spatial_mentions
    common_fields = {
        "fact_type",
        "semantic_type",
        "description",
        "target_name",
        "aliases",
        "spatial_mentions",
        "value",
        "unit",
        "counting_basis",
        "related_observation_ids",
        "constraint_refs",
        "source_feature_ids",
        "source_segment_ids",
        "source_quote",
        "source_refs",
        "confidence",
        "status",
    }
    variant_fields = {
        "spatial_entity": {"entity_type", "name", "locator", "scale"},
        "spatial_relation": {"subject_ref", "predicate", "object_ref"},
        "scoped_metric": {"metric", "scope"},
        "demand": {"demand_type", "scope", "beneficiary", "spatial_requirement"},
        "constraint": {"constraint_type", "applies_to_scope", "strength"},
        "risk": {"subject", "scope"},
        "opportunity": {"subject", "scope"},
        "document_observation": {"subject", "scope"},
    }
    allowed_fields = common_fields | variant_fields.get(fact_type, set())
    return {
        key: value
        for key, value in payload.items()
        if key in allowed_fields
    }


def normalize_l1_observation_provider_output(
    dimension_key: str,
    value: Any,
) -> "L1ObservationPassOutput":
    """Project a provider envelope into the internal recovery contract."""

    response_model = l1_observation_output_model_for_dimension(dimension_key)
    payload = value.model_dump(mode="python") if hasattr(value, "model_dump") else value
    payload = dict(payload or {})
    diagnostics = [
        str(item).strip()
        for item in (payload.get("diagnostics") or [])
        if str(item).strip()
    ]
    raw_observations = payload.get("observations") or []
    payload["observations"] = [
        _normalize_provider_observation(
            item,
            ordinal=index,
            diagnostics=diagnostics,
        )
        for index, item in enumerate(raw_observations)
    ]
    payload["diagnostics"] = list(dict.fromkeys(diagnostics))
    return response_model.model_validate(payload)


def l1_observation_output_model_for_dimension(
    dimension_key: str,
) -> type["L1ObservationPassOutput"]:
    """Return the strict observe response model for one dimension."""

    from app.modules.l1.dimension_contracts import get_dimension_semantic_contract

    contract = get_dimension_semantic_contract(dimension_key, 1)
    allowed = tuple(contract.get("l1_fact_types", []) or [])
    required = tuple(contract.get("l1_required_fact_types", []) or [])
    return build_l1_observation_output_model(
        allowed,
        required_fact_types=required,
    )


def observation_to_compiler_payload(raw: Any) -> dict[str, Any]:
    """Project one typed fact into the compiler's stable semantic view."""

    from pydantic import TypeAdapter

    adapter = TypeAdapter(L1PlanningFactDraft)
    observation = adapter.validate_python(
        raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
    )
    payload = observation.model_dump(mode="json")
    if isinstance(observation, L1SpatialEntityFact):
        payload.update({
            "entity_type": observation.entity_type,
            "name": observation.name,
            "target_name": observation.target_name or observation.name,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scale": observation.scale,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1SpatialRelationFact):
        payload.update({
            "entity_type": "",
            "name": observation.subject_ref,
            "target_name": observation.target_name or observation.subject_ref,
            "location": observation.object_ref,
            "relation": observation.predicate,
        })
    elif isinstance(observation, L1ScopedMetricFact):
        payload.update({
            "name": observation.metric,
            "target_name": observation.target_name or observation.metric,
            "location": "",
            "relation": "",
            "scope": observation.scope,
        })
    elif isinstance(observation, L1DemandFact):
        payload.update({
            "name": observation.demand_type,
            "target_name": observation.target_name,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1ConstraintFact):
        payload.update({
            "name": observation.constraint_type,
            "target_name": observation.target_name or observation.constraint_type,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.applies_to_scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1RiskOpportunityFact):
        payload.update({
            "name": observation.subject,
            "target_name": observation.target_name or observation.subject,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1DocumentObservationFact):
        payload.update({
            "name": observation.subject,
            "target_name": observation.target_name or observation.subject,
            "location": "",
            "relation": "",
            "scope": observation.scope,
        })
    return payload


class L1ObservationPassOutput(BaseModel):
    """L1 semantic extraction pass without a human report projection."""

    model_config = ConfigDict(extra="forbid")

    observations: list[L1PlanningFactDraft] = Field(default_factory=list)
    provisional_fact_records: list[L1PlanningFactDraft] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    quarantined_observations: list["QuarantinedObservation"] = Field(default_factory=list)
    allowed_fact_types: tuple[str, ...] = ()
    required_fact_types: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        allowed_fact_types = _normalize_fact_type_names(
            payload.get("allowed_fact_types")
            or cls.model_fields["allowed_fact_types"].default
            or ()
        )
        required_fact_types = tuple(
            value
            for value in _normalize_fact_type_names(
                payload.get("required_fact_types")
                or cls.model_fields["required_fact_types"].default
                or ()
            )
            if value in allowed_fact_types
        )
        diagnostics = _normalize_string_list(
            payload.get("diagnostics", []),
            field_name="diagnostics",
        )
        quarantined = list(payload.get("quarantined_observations") or [])
        if "observations" not in payload:
            payload["diagnostics"] = diagnostics
            payload["quarantined_observations"] = quarantined
            payload["allowed_fact_types"] = allowed_fact_types
            payload["required_fact_types"] = required_fact_types
            return payload
        raw_observations = _normalize_sequence_container(
            payload.get("observations", []),
            field_name="observations",
        )
        recovered: list[dict[str, Any]] = []
        provisional: list[dict[str, Any]] = []
        adapter = (
            _fact_adapter_for_allowed_fact_types(allowed_fact_types)
            if allowed_fact_types
            else None
        )
        for index, item in enumerate(raw_observations):
            try:
                if adapter is None:
                    raise ValueError("unconfigured L1 observation contract")
                fact = adapter.validate_python(item)
            except Exception as exc:
                issue_count = 1
                errors = getattr(exc, "errors", None)
                if callable(errors):
                    try:
                        issue_count = max(1, len(errors()))
                    except Exception:
                        issue_count = 1
                diagnostics.append(
                    f"l1_observation_record_invalid:{index}:{issue_count}"
                )
                diagnostics.extend(_quarantine_reason_codes(exc))
                quarantined.append(
                    QuarantinedObservation(
                        ordinal=index,
                        payload_digest=_payload_digest(item),
                        error_paths=_quarantine_error_paths(item, exc),
                        raw_payload=_safe_payload_copy(item),
                    ).model_dump(mode="json")
                )
                continue
            fact_payload = fact.model_dump(mode="json")
            recovered.append(fact_payload)
            if str(fact_payload.get("status") or "").strip() != "confirmed":
                provisional.append(fact_payload)
        confirmed_fact_types = {
            str(item.get("fact_type") or "").strip()
            for item in recovered
            if str(item.get("status") or "").strip() == "confirmed"
        }
        for fact_type in required_fact_types:
            if fact_type not in confirmed_fact_types:
                diagnostics.append(f"l1_required_fact_type_missing:{fact_type}")
        payload["observations"] = recovered
        payload["provisional_fact_records"] = provisional
        payload["diagnostics"] = diagnostics
        payload["quarantined_observations"] = quarantined
        payload["allowed_fact_types"] = allowed_fact_types
        payload["required_fact_types"] = required_fact_types
        return payload


class QuarantinedObservation(BaseModel):
    """A bad observation row captured without admitting it as a typed fact."""

    model_config = ConfigDict(extra="forbid")

    ordinal: int
    payload_digest: str
    error_paths: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | list[Any] | str | int | float | bool | None = None


class L1ReportOutput(BaseModel):
    """L1 human report synthesized from validated observations and evidence."""

    report_body: str = Field(min_length=1)


class L1SemanticOutput(BaseModel):
    """Canonical semantic result of one L1 dimension run.

    This envelope is application-owned.  The provider wire response remains
    the smaller ``L1ObservationProviderOutput``; only observations that have
    crossed local schema and source validation enter this semantic envelope.
    """

    model_config = ConfigDict(extra="forbid")

    context: L1InputContext
    observations: list[L1PlanningFactDraft] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    status: Literal["running", "complete", "diagnostic"] = "complete"
    output_digest: str = ""

    @model_validator(mode="after")
    def canonicalize_output_digest(self) -> "L1SemanticOutput":
        if self.accepted_count != len(self.observations):
            raise ValueError("L1 accepted_count must equal validated observations")
        identity = self.model_dump(mode="json", exclude={"output_digest"})
        expected = "sha256:" + _payload_digest(identity)
        if self.output_digest and self.output_digest != expected:
            raise ValueError("L1 output_digest does not match semantic output")
        self.output_digest = expected
        self.diagnostics = list(dict.fromkeys(
            str(value).strip()
            for value in self.diagnostics
            if str(value).strip()
        ))
        return self


class L1DisplayProjection(BaseModel):
    """Human-readable L1 report kept outside the semantic output chain."""

    model_config = ConfigDict(extra="forbid")

    report_body: str = ""
    input_digest: str = ""
    source_observation_count: int = Field(default=0, ge=0)
    report_digest: str = ""

    @model_validator(mode="after")
    def canonicalize_report_digest(self) -> "L1DisplayProjection":
        identity = self.model_dump(mode="json", exclude={"report_digest"})
        expected = "sha256:" + _payload_digest(identity)
        if self.report_digest and self.report_digest != expected:
            raise ValueError("L1 report_digest does not match display projection")
        self.report_digest = expected
        return self


class L1DimensionOutput(BaseModel):
    """Unified application output with separate semantic and display ports."""

    model_config = ConfigDict(extra="forbid")

    semantic: L1SemanticOutput
    display: L1DisplayProjection = Field(default_factory=L1DisplayProjection)

    @model_validator(mode="before")
    @classmethod
    def bind_display_to_semantic_context(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        semantic = payload.get("semantic")
        if hasattr(semantic, "model_dump"):
            semantic = semantic.model_dump(mode="python")
        display = payload.get("display")
        if hasattr(display, "model_dump"):
            display = display.model_dump(mode="python")
        semantic = semantic if isinstance(semantic, dict) else {}
        context = semantic.get("context")
        if hasattr(context, "model_dump"):
            context = context.model_dump(mode="python")
        context = context if isinstance(context, dict) else {}
        display = dict(display) if isinstance(display, dict) else {}
        if not display.get("input_digest"):
            display["input_digest"] = context.get("input_digest", "")
        if "source_observation_count" not in display:
            display["source_observation_count"] = len(
                semantic.get("observations") or []
            )
        if display.get("input_digest") != context.get("input_digest", ""):
            display["report_digest"] = ""
        payload["display"] = display
        return payload

    @model_validator(mode="after")
    def validate_boundary_alignment(self) -> "L1DimensionOutput":
        if self.display.input_digest != self.semantic.context.input_digest:
            raise ValueError("L1 display projection is bound to another input")
        if self.display.source_observation_count != len(self.semantic.observations):
            raise ValueError("L1 display count does not match semantic output")
        return self

    @property
    def context(self) -> L1InputContext:
        """Convenience view of the single context shared by both output ports."""

        return self.semantic.context


class L1DimensionCheckpoint(BaseModel):
    """Durable L1 checkpoint carrying one context, output, and cursor."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_version: str = "l1.checkpoint.v1"
    context: L1InputContext
    output: L1DimensionOutput
    cursor: L1DimensionPassState

    @model_validator(mode="after")
    def validate_checkpoint_alignment(self) -> "L1DimensionCheckpoint":
        output_context = self.output.context
        if output_context.input_digest != self.context.input_digest:
            raise ValueError("L1 checkpoint output is bound to another input")
        if output_context.dimension_key != self.context.dimension_key:
            raise ValueError("L1 checkpoint dimension does not match context")
        if self.cursor.dimension_key != self.context.dimension_key:
            raise ValueError("L1 checkpoint cursor does not match context")
        if self.cursor.input_digest and self.cursor.input_digest != self.context.input_digest:
            raise ValueError("L1 checkpoint cursor is bound to another input")
        return self


__all__ = [
    "L1SourceEvidence",
    "L1SpatialLocator",
    "L1SpatialEntityFact",
    "L1SpatialRelationFact",
    "L1ScopedMetricFact",
    "L1DemandFact",
    "L1ConstraintFact",
    "L1RiskOpportunityFact",
    "L1RiskFact",
    "L1OpportunityFact",
    "L1DocumentObservationFact",
    "L1PlanningFactDraft",
    "build_l1_observation_output_model",
    "build_l1_observation_provider_model",
    "l1_observation_output_model_for_dimension",
    "l1_observation_provider_model_for_dimension",
    "normalize_l1_observation_provider_output",
    "observation_to_compiler_payload",
    "L1ObservationPassOutput",
    "L1ObservationProviderOutput",
    "QuarantinedObservation",
    "L1ReportOutput",
    "L1SemanticOutput",
    "L1DisplayProjection",
    "L1DimensionOutput",
    "L1DimensionCheckpoint",
]
