"""Provider-facing L1 planning fact contracts.

The observe pass emits a discriminated union.  The fact category is selected
at generation time and each category exposes only its own semantic fields.
Spatial locators are coarse evidence hints; no coordinates or geometry are
accepted at L1.
"""

from __future__ import annotations

import hashlib
import json
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

from app.contracts.domain.l1_contracts import L1SpatialMention


_TARGET_ACTION_SUFFIXES = ("修缮", "修复", "维护", "保护", "整治")


def _backfill_target_name(value: str) -> str:
    """Recover a semantic target from a structured demand label.

    This only strips a known action suffix.  It never creates a location or
    geometry and remains a compatibility fallback for older providers that do
    not emit the explicit ``target_name`` field.
    """

    text = str(value or "").strip()
    if not text or any(token in text for token in ("、", "，", ",", "；", ";", " ")):
        return ""
    for suffix in _TARGET_ACTION_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return ""


class L1SourceEvidence(BaseModel):
    """Evidence lineage shared by every L1 planning fact."""

    model_config = ConfigDict(extra="forbid")

    semantic_type: str = ""
    description: str = ""
    target_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    spatial_mentions: list[L1SpatialMention] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    related_observation_ids: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    source_refs: list[str] = Field(default_factory=list)
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


class L1SpatialLocator(BaseModel):
    """Coarse spatial evidence, never a coordinate or geometry."""

    model_config = ConfigDict(extra="forbid")

    place_names: list[str] = Field(default_factory=list)
    relation: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)


class L1SpatialEntityFact(L1SourceEvidence):
    fact_type: Literal["spatial_entity"]
    entity_type: str
    name: str
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)
    scale: str = ""


class L1SpatialRelationFact(L1SourceEvidence):
    fact_type: Literal["spatial_relation"]
    subject_ref: str
    predicate: str
    object_ref: str


class L1ScopedMetricFact(L1SourceEvidence):
    fact_type: Literal["scoped_metric"]
    metric: str
    scope: str


class L1DemandFact(L1SourceEvidence):
    fact_type: Literal["demand"]
    demand_type: str
    scope: str
    beneficiary: str = ""
    spatial_requirement: Literal["none", "place_binding", "demand_points"] = "none"
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)


class L1ConstraintFact(L1SourceEvidence):
    fact_type: Literal["constraint"]
    constraint_type: str
    applies_to_scope: str
    strength: Literal["hard", "soft", "unknown"] = "unknown"
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)


class L1RiskOpportunityFact(L1SourceEvidence):
    fact_type: Literal["risk", "opportunity"]
    subject: str
    scope: str
    locator: L1SpatialLocator = Field(default_factory=L1SpatialLocator)


class L1RiskFact(L1RiskOpportunityFact):
    fact_type: Literal["risk"]


class L1OpportunityFact(L1RiskOpportunityFact):
    fact_type: Literal["opportunity"]


class L1DocumentObservationFact(L1SourceEvidence):
    fact_type: Literal["document_observation"]
    subject: str
    scope: str


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

    candidate = value.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].lstrip()
    return json.loads(candidate)


def _normalize_sequence_container(
    value: Any,
    *,
    field_name: str,
) -> list[Any]:
    """Accept common provider list containers at the typed boundary."""

    candidate = value
    if isinstance(candidate, str):
        candidate = _decode_json_container(candidate)
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


@lru_cache(maxsize=None)
def build_l1_observation_output_model(
    allowed_fact_types: tuple[str, ...],
    *,
    required_fact_types: tuple[str, ...] = (),
) -> type["L1ObservationPassOutput"]:
    """Build the smallest strict observe response model for one dimension.

    The provider must choose from a discriminated union.  Sending seven
    branches to every dimension needlessly increases the tool schema and makes
    malformed envelopes (notably a JSON array serialized as a string) more
    likely.  This factory keeps the same strict branch models while narrowing
    the union to the dimension contract.
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


def l1_observation_output_model_for_dimension(
    dimension_key: str,
) -> type["L1ObservationPassOutput"]:
    """Return the strict observe response model for one dimension."""

    from app.domain.assessment.dimension_contracts import get_dimension_semantic_contract

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
            "target_name": observation.target_name or _backfill_target_name(observation.demand_type),
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
    "l1_observation_output_model_for_dimension",
    "observation_to_compiler_payload",
    "L1ObservationPassOutput",
    "QuarantinedObservation",
    "L1ReportOutput",
]
