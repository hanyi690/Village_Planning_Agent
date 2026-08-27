"""Provider-facing and internal L1 planning fact contracts.

The internal observe result is a discriminated union.  The provider wire
result is deliberately flatter: it carries a stable fact_type and optional
semantic fields, while branch requirements and dimension membership are
validated locally.  Spatial locators are coarse evidence hints; no
coordinates or geometry are accepted at L1.
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

from app.contracts.json_container import decode_json_container
from app.contracts.domain.l1_contracts import LocationMentionDraft


class L1SourceEvidence(BaseModel):
    """Evidence lineage shared by every L1 planning fact."""

    model_config = ConfigDict(extra="forbid")

    semantic_type: str = ""
    description: str = ""
    target_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    spatial_mentions: list[LocationMentionDraft] = Field(default_factory=list)
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


class L1ProviderSpatialLocator(BaseModel):
    """Provider wire locator; scalar fields may arrive as null."""

    model_config = ConfigDict(extra="ignore")

    place_names: list[str] | None = None
    relation: str | None = None
    source_feature_ids: list[str] | None = None


class L1ProviderSourceEvidence(BaseModel):
    """Provider wire evidence with tolerant transport scalar boundaries."""

    model_config = ConfigDict(extra="ignore")

    semantic_type: str | None = None
    description: str | None = None
    target_name: str | None = None
    aliases: list[str] | None = None
    spatial_mentions: list[dict[str, Any]] | None = None
    attributes: dict[str, Any] | None = None
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
            "source_segment_ids",
            "source_refs",
        ):
            if field_name in payload and isinstance(payload[field_name], str):
                payload[field_name] = _decode_json_container(payload[field_name])
        return payload


class L1ProviderObservation(L1ProviderSourceEvidence):
    """Flat provider wire item; strict variant validation stays local."""

    fact_type: Literal[
        "spatial_entity",
        "spatial_relation",
        "scoped_metric",
        "demand",
        "constraint",
        "risk",
        "opportunity",
        "document_observation",
    ]
    entity_type: str | None = None
    name: str | None = None
    locator: L1ProviderSpatialLocator | None = None
    scale: str | None = None
    subject_ref: str | None = None
    predicate: str | None = None
    object_ref: str | None = None
    metric: str | None = None
    scope: str | None = None
    demand_type: str | None = None
    beneficiary: str | None = None
    spatial_requirement: str | None = None
    constraint_type: str | None = None
    applies_to_scope: str | None = None
    strength: str | None = None
    subject: str | None = None


class L1ObservationProviderOutput(BaseModel):
    """Minimal provider envelope for the L1 observe pass.

    Quarantine, provisional records, and dimension coverage are deterministic
    application state.  They are deliberately not exposed in the provider
    tool schema; otherwise the model sees an internal recovery envelope and a
    semantic output envelope as one contract.
    """

    model_config = ConfigDict(extra="ignore")

    observations: list[L1ProviderObservation] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def decode_provider_containers(cls, data: Any) -> Any:
        """Normalize provider JSON containers before wire validation."""

        if not isinstance(data, dict):
            return data
        payload = dict(data)
        # A non-object item in the observations array is provider wire noise,
        # not an observation.  Drop it at the wire boundary so it cannot be
        # mistaken for a fact; the source/fact validators remain responsible
        # for accepting or quarantining actual observation objects.
        if isinstance(payload.get("observations"), list):
            payload["observations"] = [
                item for item in payload["observations"] if isinstance(item, dict)
            ]
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

    from app.domain.assessment.dimension_contracts import get_dimension_semantic_contract

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


def _provider_attributes(value: Any, *, diagnostics: list[str], ordinal: int) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _provider_string(raw_key)
        if not key:
            continue
        if isinstance(raw_value, (str, int, float, bool)):
            result[key] = str(raw_value)
        else:
            result[key] = json.dumps(
                raw_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            diagnostics.append(f"l1_provider_attribute_coerced:{ordinal}:{key}")
    return result


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

_SPATIAL_MENTION_KIND_ALIASES = {
    "target": "target",
    "place": "place",
    "anchor_request": "anchor_request",
    "anchor": "anchor_request",
    "target_place": "place",
}

_SPATIAL_RESOLUTION_ALIASES = {
    "resolved": "resolved",
    "verified": "resolved",
    "confirmed": "resolved",
    "needs_retrieval": "needs_retrieval",
    "pending": "needs_retrieval",
    "unresolved": "needs_retrieval",
    "conflict": "conflict",
    "source_exhausted": "source_exhausted",
    "exhausted": "source_exhausted",
    "unknown": "unknown",
}

_SPATIAL_SCOPE_ROLE_ALIASES = {
    "natural_village": "natural_village",
    "village": "natural_village",
    "natural village": "natural_village",
    "自然村": "natural_village",
    "村庄": "natural_village",
    "administrative_village": "administrative_village",
    "administrative village": "administrative_village",
    "行政村": "administrative_village",
    "place": "place",
    "地点": "place",
    "area": "area",
    "区域": "area",
}


def _provider_locator(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "place_names": _provider_string_list(value.get("place_names")),
        "relation": _provider_string(value.get("relation")),
        "source_feature_ids": _provider_string_list(value.get("source_feature_ids")),
    }


def _provider_spatial_mentions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = _decode_json_container(candidate)
        except Exception:
            return []
    if not isinstance(candidate, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in candidate:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        for field_name in (
            "mention",
            "normalized_name",
            "target_name",
            "role",
            "relation",
            "instance_label",
            "instance_count",
        ):
            item[field_name] = _provider_string(item.get(field_name))
        mention_kind = _provider_string(item.get("mention_kind")).casefold()
        item["mention_kind"] = _SPATIAL_MENTION_KIND_ALIASES.get(
            mention_kind,
            "target",
        )
        resolution_state = _provider_string(item.get("resolution_state")).casefold()
        item["resolution_state"] = _SPATIAL_RESOLUTION_ALIASES.get(
            resolution_state,
            "needs_retrieval",
        )
        item["aliases"] = _provider_string_list(item.get("aliases"))
        item["village_scopes"] = _provider_string_list(item.get("village_scopes"))
        item["place_scopes"] = _provider_string_list(item.get("place_scopes"))
        item["source_feature_ids"] = _provider_string_list(item.get("source_feature_ids"))
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        item["provenance"] = {
            "source_refs": _provider_string_list(provenance.get("source_refs")),
            "source_segment_ids": _provider_string_list(provenance.get("source_segment_ids")),
            "source_quote": _provider_string(provenance.get("source_quote")),
            "observation_id": _provider_string(provenance.get("observation_id")),
        }
        result.append(item)
    return result


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
    ):
        payload[field_name] = _provider_string(payload.get(field_name))
    for field_name in (
        "aliases",
        "related_observation_ids",
        "constraint_refs",
        "source_feature_ids",
        "source_segment_ids",
        "source_refs",
    ):
        payload[field_name] = _provider_string_list(payload.get(field_name))
    payload["unit"] = _provider_string(payload.get("unit"))
    payload["counting_basis"] = _provider_string(payload.get("counting_basis"))
    payload["attributes"] = _provider_attributes(
        payload.get("attributes"),
        diagnostics=diagnostics,
        ordinal=ordinal,
    )
    payload["spatial_mentions"] = _provider_spatial_mentions(
        payload.get("spatial_mentions")
    )
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
    if fact_type in {"spatial_entity", "demand", "constraint", "risk", "opportunity"}:
        payload["locator"] = _provider_locator(payload.get("locator"))
    if fact_type == "demand" and payload.get("spatial_requirement") is None:
        payload["spatial_requirement"] = "none"
    if fact_type == "constraint" and payload.get("strength") is None:
        payload["strength"] = "unknown"
    common_fields = {
        "fact_type",
        "semantic_type",
        "description",
        "target_name",
        "aliases",
        "spatial_mentions",
        "attributes",
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
        "demand": {"demand_type", "scope", "beneficiary", "spatial_requirement", "locator"},
        "constraint": {"constraint_type", "applies_to_scope", "strength", "locator"},
        "risk": {"subject", "scope", "locator"},
        "opportunity": {"subject", "scope", "locator"},
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
    "build_l1_observation_provider_model",
    "l1_observation_output_model_for_dimension",
    "l1_observation_provider_model_for_dimension",
    "normalize_l1_observation_provider_output",
    "observation_to_compiler_payload",
    "L1ObservationPassOutput",
    "L1ObservationProviderOutput",
    "QuarantinedObservation",
    "L1ReportOutput",
]
