"""Provider-facing L1 planning fact contracts.

The observe pass emits a discriminated union.  The fact category is selected
at generation time and each category exposes only its own semantic fields.
Spatial locators are coarse evidence hints; no coordinates or geometry are
accepted at L1.
"""

from __future__ import annotations

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


class L1SourceEvidence(BaseModel):
    """Evidence lineage shared by every L1 planning fact."""

    model_config = ConfigDict(extra="forbid")

    semantic_type: str = ""
    description: str = ""
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
    status: Literal["confirmed", "uncertain", "conflict", "source_exhausted"] = "confirmed"

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


def _legacy_compiler_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize pre-union persisted observations for compiler-only consumers."""

    payload = dict(raw)
    entity_type = str(payload.get("entity_type") or "").strip()
    name = str(payload.get("name") or payload.get("subject") or "").strip()
    location = str(payload.get("location") or "").strip()
    relation = str(payload.get("relation") or "").strip()
    if not str(payload.get("fact_type") or "").strip():
        if all(
            str(payload.get(field) or "").strip()
            for field in ("subject_ref", "predicate", "object_ref")
        ):
            payload["fact_type"] = "spatial_relation"
        elif str(payload.get("metric") or "").strip():
            payload["fact_type"] = "scoped_metric"
        elif str(payload.get("demand_type") or "").strip():
            payload["fact_type"] = "demand"
        elif str(payload.get("constraint_type") or "").strip():
            payload["fact_type"] = "constraint"
        elif str(payload.get("subject") or "").strip() and str(
            payload.get("scope") or ""
        ).strip() and not any((entity_type, location, relation)):
            payload["fact_type"] = "document_observation"
        else:
            payload["fact_type"] = "spatial_entity"
    payload.setdefault("semantic_type", str(payload.get("semantic_type") or "").strip())
    payload.setdefault("description", str(payload.get("description") or "").strip())
    payload.setdefault("attributes", payload.get("attributes") or {})
    payload.setdefault("value", payload.get("value"))
    payload.setdefault("unit", str(payload.get("unit") or "").strip())
    payload.setdefault(
        "counting_basis",
        str(payload.get("counting_basis") or "").strip(),
    )
    payload["related_observation_ids"] = _normalize_string_list(
        payload.get("related_observation_ids", []),
        field_name="related_observation_ids",
    )
    payload["constraint_refs"] = _normalize_string_list(
        payload.get("constraint_refs", []),
        field_name="constraint_refs",
    )
    payload["source_feature_ids"] = _normalize_string_list(
        payload.get("source_feature_ids", []),
        field_name="source_feature_ids",
    )
    payload["source_segment_ids"] = _normalize_string_list(
        payload.get("source_segment_ids", []),
        field_name="source_segment_ids",
    )
    payload["source_refs"] = _normalize_string_list(
        payload.get("source_refs", []),
        field_name="source_refs",
    )
    payload["source_quote"] = str(payload.get("source_quote") or "").strip()
    payload["status"] = str(payload.get("status") or "confirmed").strip()
    payload["confidence"] = payload.get("confidence")

    fact_type = str(payload.get("fact_type") or "").strip()
    if fact_type == "spatial_entity":
        payload["entity_type"] = entity_type
        payload["name"] = name
        payload["location"] = location
        payload["relation"] = relation
        payload["scale"] = str(payload.get("scale") or "").strip()
    elif fact_type == "spatial_relation":
        payload["subject_ref"] = str(payload.get("subject_ref") or name).strip()
        payload["predicate"] = str(payload.get("predicate") or relation).strip()
        payload["object_ref"] = str(payload.get("object_ref") or location).strip()
        payload["name"] = payload["subject_ref"]
        payload["location"] = payload["object_ref"]
        payload["relation"] = payload["predicate"]
    elif fact_type == "scoped_metric":
        payload["metric"] = str(payload.get("metric") or name).strip()
        payload["scope"] = str(payload.get("scope") or location or "全村").strip()
        payload["name"] = payload["metric"]
        payload["location"] = ""
        payload["relation"] = ""
    elif fact_type == "demand":
        payload["demand_type"] = str(payload.get("demand_type") or name).strip()
        payload["scope"] = str(payload.get("scope") or location or "全村").strip()
        payload["name"] = payload["demand_type"]
        payload["location"] = location
        payload["relation"] = relation
    elif fact_type == "constraint":
        payload["constraint_type"] = str(
            payload.get("constraint_type") or name
        ).strip()
        payload["applies_to_scope"] = str(
            payload.get("applies_to_scope") or payload.get("scope") or location or "全村"
        ).strip()
        payload["name"] = payload["constraint_type"]
        payload["location"] = location
        payload["relation"] = relation
    elif fact_type in {"risk", "opportunity"}:
        payload["subject"] = str(payload.get("subject") or name).strip()
        payload["scope"] = str(payload.get("scope") or location or "全村").strip()
        payload["name"] = payload["subject"]
        payload["location"] = location
        payload["relation"] = relation
    elif fact_type == "document_observation":
        payload["subject"] = str(payload.get("subject") or name).strip()
        payload["scope"] = str(payload.get("scope") or location or "全村").strip()
        payload["name"] = payload["subject"]
        payload["location"] = ""
        payload["relation"] = ""
    return payload


@lru_cache(maxsize=None)
def build_l1_observation_output_model(
    allowed_fact_types: tuple[str, ...],
) -> type["L1ObservationPassOutput"]:
    """Build the smallest strict observe response model for one dimension.

    The provider must choose from a discriminated union.  Sending seven
    branches to every dimension needlessly increases the tool schema and makes
    malformed envelopes (notably a JSON array serialized as a string) more
    likely.  This factory keeps the same strict branch models while narrowing
    the union to the dimension contract.
    """

    normalized = tuple(dict.fromkeys(str(value).strip() for value in allowed_fact_types))
    if not normalized:
        raise ValueError("at least one L1 fact_type is required")
    selected = tuple(_FACT_TYPE_MODELS.get(value) for value in normalized)
    if any(model is None for model in selected):
        unknown = [value for value, model in zip(normalized, selected) if model is None]
        raise ValueError(f"unknown L1 fact_type(s): {unknown}")
    selected_models = tuple(model for model in selected if model is not None)
    all_models = tuple(dict.fromkeys(_FACT_TYPE_MODELS.values()))
    if set(selected_models) == set(all_models):
        return L1ObservationPassOutput

    union_type = Union.__getitem__(selected_models)
    fact_type_union = Annotated[union_type, Field(discriminator="fact_type")]
    suffix = "_" + "_".join(normalized)
    model_name = f"L1ObservationPassOutput{suffix}"
    return create_model(
        model_name,
        __base__=L1ObservationPassOutput,
        __module__=__name__,
        observations=(list[fact_type_union], Field(default_factory=list)),
    )


def l1_observation_output_model_for_dimension(
    dimension_key: str,
) -> type["L1ObservationPassOutput"]:
    """Return the global L1 fact union; dimension scope stays diagnostic-only."""

    _ = dimension_key
    return L1ObservationPassOutput


def observation_to_compiler_payload(raw: Any) -> dict[str, Any]:
    """Project one typed fact into the compiler's stable semantic view."""

    from pydantic import TypeAdapter

    if isinstance(raw, dict) and not str(raw.get("fact_type") or "").strip():
        return _legacy_compiler_payload(raw)

    adapter = TypeAdapter(L1PlanningFactDraft)
    observation = adapter.validate_python(
        raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
    )
    payload = observation.model_dump(mode="json")
    if isinstance(observation, L1SpatialEntityFact):
        payload.update({
            "entity_type": observation.entity_type,
            "name": observation.name,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scale": observation.scale,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1SpatialRelationFact):
        payload.update({
            "entity_type": "",
            "name": observation.subject_ref,
            "location": observation.object_ref,
            "relation": observation.predicate,
        })
    elif isinstance(observation, L1ScopedMetricFact):
        payload.update({
            "name": observation.metric,
            "location": "",
            "relation": "",
            "scope": observation.scope,
        })
    elif isinstance(observation, L1DemandFact):
        payload.update({
            "name": observation.demand_type,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1ConstraintFact):
        payload.update({
            "name": observation.constraint_type,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.applies_to_scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1RiskOpportunityFact):
        payload.update({
            "name": observation.subject,
            "location": "、".join(observation.locator.place_names),
            "relation": observation.locator.relation,
            "scope": observation.scope,
            "source_feature_ids": observation.locator.source_feature_ids,
        })
    elif isinstance(observation, L1DocumentObservationFact):
        payload.update({
            "name": observation.subject,
            "location": "",
            "relation": "",
            "scope": observation.scope,
        })
    return payload


class L1ObservationPassOutput(BaseModel):
    """L1 semantic extraction pass without a human report projection."""

    model_config = ConfigDict(extra="forbid")

    observations: list[L1PlanningFactDraft] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        diagnostics = _normalize_string_list(
            payload.get("diagnostics", []),
            field_name="diagnostics",
        )
        if "observations" not in payload:
            payload["diagnostics"] = diagnostics
            return payload
        raw_observations = _normalize_sequence_container(
            payload.get("observations", []),
            field_name="observations",
        )
        recovered: list[dict[str, Any]] = []
        for index, item in enumerate(raw_observations):
            try:
                fact = _FACT_ADAPTER.validate_python(item)
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
                continue
            recovered.append(fact.model_dump(mode="json"))
        payload["observations"] = recovered
        payload["diagnostics"] = diagnostics
        return payload


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
    "L1ReportOutput",
]
