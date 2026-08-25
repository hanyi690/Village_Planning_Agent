"""Provider-facing planning claim drafts and their domain normalization.

The LLM is allowed to be incomplete or semantically imprecise at this
boundary.  It is not allowed to create an executable target.  This module is
the only place that converts provider drafts into the strict claim contract.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.contracts.program import (
    PlanningClaim,
    PlanningClaimSet,
    PlanningSpatialRequirements,
)
from app.contracts.domain.planning_semantics import (
    AxisPlanningParameters,
    FacilityPlanningParameters,
    LinearAssetPlanningParameters,
    PolygonPlanningParameters,
    SiteAreaPlanningParameters,
    RoadPlanningParameters,
)


class MeasureDraft(BaseModel):
    """Provider-facing value and source unit; normalization happens later."""

    value: float | None = None
    unit: str = ""


class MeasureRangeDraft(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""


PlanningCategoryDraft: TypeAlias = Literal[
    "site_area",
    "facility",
    "road",
    "axis",
    "restoration",
    "protection",
    "zone",
    "action",
]
PlanningOutputDraft: TypeAlias = Literal[
    "parcel",
    "polygon",
    "point",
    "line",
    "action",
]
PlanningActionDraft: TypeAlias = Literal[
    "preserve",
    "new",
    "expand",
    "relocate",
    "upgrade",
    "widen",
    "harden",
    "repair",
    "demolish",
]
PlanningRoleDraft: TypeAlias = Literal[
    "evidence_statement",
    "indicator",
    "constraint",
    "objective",
    "non_spatial_action",
    "project_package",
    "spatial_intervention",
]


class RoadPlanningParametersDraft(BaseModel):
    action: Literal["preserve", "new", "upgrade", "widen", "harden", "repair"] = "new"
    road_level: str = ""
    length: MeasureDraft | None = None
    roadbed_width: MeasureDraft | None = None
    pavement_width: MeasureDraft | None = None
    alignment_refs: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)

    @field_validator("alignment_refs", "connects", mode="before")
    @classmethod
    def decode_refs(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value

    @field_validator("length", "roadbed_width", "pavement_width", mode="before")
    @classmethod
    def decode_measures(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class LinearAssetPlanningParametersDraft(BaseModel):
    action: Literal["preserve", "new", "upgrade", "expand", "repair"] = "new"
    length: MeasureDraft | None = None
    diameter: MeasureDraft | None = None
    material: str = ""
    alignment_refs: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)

    @field_validator("alignment_refs", "connects", mode="before")
    @classmethod
    def decode_refs(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value

    @field_validator("length", "diameter", mode="before")
    @classmethod
    def decode_measures(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class FacilityPlanningParametersDraft(BaseModel):
    facility_type: str = ""
    action: PlanningActionDraft = "new"
    service_radius: MeasureDraft | None = None
    capacity: MeasureDraft | None = None
    footprint_area: MeasureDraft | None = None

    @field_validator("service_radius", "capacity", "footprint_area", mode="before")
    @classmethod
    def decode_measures(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class AxisPlanningParametersDraft(BaseModel):
    action: Literal["preserve", "new", "upgrade"] = "new"
    axis_type: Literal["primary", "secondary", "spatial_control"] = "primary"
    direction: str = ""
    reference_features: list[str] = Field(default_factory=list)
    connects: list[str] = Field(default_factory=list)
    corridor_width: MeasureDraft | None = None

    @field_validator("reference_features", "connects", mode="before")
    @classmethod
    def decode_refs(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value

    @field_validator("corridor_width", mode="before")
    @classmethod
    def decode_measure(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class PolygonPlanningParametersDraft(BaseModel):
    materialization_role: Literal[
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    ] | None = None
    planning_zone: str = ""
    land_use: str = ""
    area_range: MeasureRangeDraft | None = None

    @field_validator("area_range", mode="before")
    @classmethod
    def decode_range(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class SiteAreaPlanningParametersDraft(BaseModel):
    site_type: str = Field(
        default="",
    )
    action: PlanningActionDraft = "new"
    capacity: MeasureDraft | None = None
    footprint_area: MeasureDraft | None = None

    @field_validator("capacity", "footprint_area", mode="before")
    @classmethod
    def decode_measures(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
        return value


class PlanningClaimDraft(BaseModel):
    """Typed but non-authoritative provider output.

    The fields which commonly arrive as ``null`` or provider-specific strings
    deliberately remain permissive here.  Strict category/output invariants
    belong to ``PlanningClaim`` after normalization.
    """

    claim_id: str = ""
    dimension_key: str = ""
    statement: str = ""
    planning_role: PlanningRoleDraft = "evidence_statement"
    project_package_ref: str = ""
    affected_population: float | None = None
    affected_parcel_refs: list[str] = Field(default_factory=list)
    suggested_category: PlanningCategoryDraft = "action"
    suggested_output_kind: PlanningOutputDraft = "action"
    asset_kind: Literal[
        "none", "facility", "land_use", "axis", "road",
        "water_supply", "sewer", "stormwater", "power", "communication",
        "drainage_channel", "revetment",
    ] = "none"
    suggested_interventions: list[str] = Field(default_factory=list)
    quantity: float | None = None
    quantity_unit: str | None = None
    intervention_action: PlanningActionDraft = "new"
    road_parameters: RoadPlanningParametersDraft | None = None
    linear_parameters: LinearAssetPlanningParametersDraft | None = None
    facility_parameters: FacilityPlanningParametersDraft | None = None
    axis_parameters: AxisPlanningParametersDraft | None = None
    polygon_parameters: PolygonPlanningParametersDraft | None = None
    site_area_parameters: SiteAreaPlanningParametersDraft | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    location_hints: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    objective_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    spatial_requirements: PlanningSpatialRequirements | None = None
    confidence: float | None = None
    uncertainty: str = ""

    @field_validator(
        "affected_parcel_refs",
        "suggested_interventions",
        "location_hints",
        "constraint_refs",
        "objective_refs",
        "evidence_refs",
        "source_fact_refs",
        "source_refs",
        mode="before",
    )
    @classmethod
    def decode_list_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            decoded = _decode_json_container(value)
            if not isinstance(decoded, list):
                raise TypeError("structured list argument must decode to a list")
            return decoded
        return value

    @field_validator(
        "road_parameters",
        "facility_parameters",
        "axis_parameters",
        "polygon_parameters",
        "site_area_parameters",
        "spatial_requirements",
        mode="before",
    )
    @classmethod
    def decode_parameter_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            decoded = _decode_json_container(value)
            if not isinstance(decoded, dict):
                raise TypeError("structured parameter argument must decode to an object")
            return decoded
        return value


class PlanningClaimDraftSet(BaseModel):
    """Provider response before domain validation."""

    schema_version: str = "2.0"
    dimension_key: str = ""
    claims: list[PlanningClaimDraft] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    @field_validator("claims", mode="before")
    @classmethod
    def decode_claims(cls, value: Any) -> Any:
        """Decode the provider's JSON-string tool argument at one boundary.

        OpenAI-compatible providers are allowed to serialize a nested tool
        argument even when the outer tool call is structured.  The provider
        adapter must present a real list to the domain; no worker should know
        about that wire representation.
        """

        if isinstance(value, str):
            decoded = _decode_json_container(value)
            if not isinstance(decoded, list):
                raise TypeError("structured claims argument must decode to a list")
            return decoded
        return value

    @field_validator("diagnostics", mode="before")
    @classmethod
    def decode_diagnostics(cls, value: Any) -> Any:
        if isinstance(value, str):
            decoded = _decode_json_container(value)
            if not isinstance(decoded, list):
                raise TypeError("structured diagnostics argument must decode to a list")
            return decoded
        return value


class L3ClaimOutput(BaseModel):
    """L3 planning-intent pass; no human report field is requested."""

    claims: list[PlanningClaimDraft] = Field(default_factory=list)

    @field_validator("claims", mode="before")
    @classmethod
    def decode_claims(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _decode_json_container(value)
            if not isinstance(value, list):
                raise TypeError("structured claims argument must decode to a list")
            return value
        return value


class L3ReportOutput(BaseModel):
    """L3 human report synthesized after claim validation."""

    report_body: str = ""


def _decode_json_container(value: str) -> Any:
    """Decode a provider JSON container without accepting executable text."""

    candidate = value.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].lstrip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        repaired = _repair_unescaped_quotes(candidate)
        if repaired == candidate:
            raise
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as repaired_exc:
            raise ValueError(
                "provider JSON container is malformed after quote repair: "
                f"{repaired_exc.msg} at column {repaired_exc.colno}"
            ) from exc


def _repair_unescaped_quotes(value: str) -> str:
    """Repair quotes inside provider strings while preserving JSON structure.

    Some OpenAI-compatible providers serialize a nested tool argument and fail
    to escape a quotation mark in a Chinese sentence.  This is deliberately a
    narrow wire-format repair: only a quote inside a string whose next token is
    not a JSON delimiter is escaped.  The repaired value is still parsed by
    ``json.loads`` before it can reach the domain contract.
    """

    chars: list[str] = []
    in_string = False
    escaped = False
    length = len(value)
    for index, char in enumerate(value):
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            chars.append(char)
            escaped = True
            continue
        if char != '"':
            chars.append(char)
            continue
        if not in_string:
            in_string = True
            chars.append(char)
            continue

        next_index = index + 1
        while next_index < length and value[next_index].isspace():
            next_index += 1
        next_char = value[next_index] if next_index < length else ""
        if next_char in {",", "]", "}", ":", ""}:
            in_string = False
            chars.append(char)
        else:
            chars.extend(("\\", '"'))
    return "".join(chars)


_CATEGORIES = {
    "site_area",
    "facility",
    "road",
    "axis",
    "restoration",
    "protection",
    "zone",
    "action",
}
_ALLOWED_OUTPUTS = {
    "facility": "point",
    "road": "line",
    "axis": "line",
    "restoration": "polygon",
    "protection": "polygon",
    "zone": "polygon",
    "action": "action",
}
_SITE_AREA_OUTPUTS = {"parcel", "polygon"}
_LINEAR_ASSETS = {
    "road",
    "water_supply",
    "sewer",
    "stormwater",
    "power",
    "communication",
    "drainage_channel",
    "revetment",
}
_OUTPUT_ALIASES = {
    "zone": "polygon",
    "area": "polygon",
    "surface": "polygon",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def _normalize_category(raw: PlanningClaimDraft, diagnostics: list[str]) -> str:
    category = _text(raw.suggested_category).lower()
    if category in _CATEGORIES:
        return category
    _diagnostic(
        diagnostics,
        "warning",
        "unsupported_category",
        raw.claim_id or "claim",
        f"unsupported category {category!r}; kept as action",
    )
    return "action"


def _raw_output_kind(raw: PlanningClaimDraft) -> str:
    return _OUTPUT_ALIASES.get(
        _text(raw.suggested_output_kind).lower(),
        _text(raw.suggested_output_kind).lower(),
    )


def _normalize_output(
    raw: PlanningClaimDraft,
    category: str,
    diagnostics: list[str],
) -> str:
    output = _raw_output_kind(raw)
    if category == "site_area":
        if output in _SITE_AREA_OUTPUTS:
            return output
        _diagnostic(
            diagnostics,
            "warning",
            "invalid_site_area_output",
            raw.claim_id or "claim",
            f"site_area output {output!r} is not executable; deferred as action",
        )
        return "action"
    expected = _ALLOWED_OUTPUTS[category]
    if output != expected:
        # Lossless normalization: the output kind is auto-corrected to the
        # category-valid value.  This is a WARNING, not an error - the claim
        # is fully usable and must not trigger a whole-dimension re-run.
        _diagnostic(
            diagnostics,
            "warning",
            "category_output_mismatch",
            raw.claim_id or "claim",
            f"{category} output {output!r} normalized to {expected!r}",
        )
    return expected


def _normalize_asset_kind(
    raw: PlanningClaimDraft,
    category: str,
    output: str,
    diagnostics: list[str],
) -> str:
    """Keep asset/category compatibility deterministic before strict validation."""
    asset = _text(raw.asset_kind).lower()
    allowed = {
        "facility": {"none", "facility"},
        "site_area": {"none"},
        "road": set(_LINEAR_ASSETS),
        "axis": {"none", "axis"},
        "restoration": {"none"},
        "protection": {"none"},
        "zone": {"none", "land_use"},
        "action": {"none"},
    }
    if asset in allowed[category]:
        return asset
    if category == "road" and output == "line" and raw.road_parameters is not None:
        # A provider may omit the redundant asset marker while carrying the
        # category-specific typed road block.
        return "road"
    fallback = {
        "facility": "facility",
        "site_area": "none",
        "axis": "axis",
        "zone": "none",
        "restoration": "none",
        "protection": "none",
        "action": "none",
    }.get(category, "none")
    if category == "road" and output == "line":
        fallback = "none"
    _diagnostic(
        diagnostics,
        "warning",
        "asset_kind_category_mismatch",
        raw.claim_id or "claim",
        f"asset_kind {asset!r} is incompatible with {category}/{output}; "
        f"normalized to {fallback!r}",
    )
    return fallback


_ACTION_SET = {
    "preserve",
    "new",
    "expand",
    "relocate",
    "upgrade",
    "widen",
    "harden",
    "repair",
    "demolish",
}
_LENGTH_TO_M = {
    "m": 1.0,
    "meter": 1.0,
    "metre": 1.0,
    "米": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometre": 1000.0,
    "公里": 1000.0,
}
_DIAMETER_TO_MM = {
    "mm": 1.0,
    "毫米": 1.0,
    "cm": 10.0,
    "厘米": 10.0,
    "m": 1000.0,
    "米": 1000.0,
}
# 计数单位若被 L3 误当作面积单位：不换算，丢弃面积约束（见 area_range 校验）。
_COUNT_AS_AREA_UNITS = {
    "个", "处", "座", "条", "棵", "株", "人", "户", "家", "间", "栋", "点", "处次", "人次",
    "m", "km", "cm", "mm",  # 长度/距离被误填为面积：属面积数值口径错误，同样丢弃
}

_AREA_TO_HA = {
    "ha": 1.0,
    "hectare": 1.0,
    "公顷": 1.0,
    "mu": 1.0 / 15.0,  # 1 亩 = 1/15 公顷
    "m2": 0.0001,
    "m²": 0.0001,
    "㎡": 0.0001,
    "平方米": 0.0001,
    "km2": 100.0,
    "km\u00b2": 100.0,
    "平方公里": 100.0,
    "平方千米": 100.0,
}
_AREA_TO_M2 = {unit: factor * 10000.0 for unit, factor in _AREA_TO_HA.items()}


def _diagnostic(
    diagnostics: list[str],
    severity: str,
    code: str,
    claim_id: str,
    message: str,
) -> None:
    diagnostics.append(f"{severity.upper()}[{code}] {claim_id}: {message}")


_TYPED_PARAMETER_FIELDS = (
    "road_parameters",
    "linear_parameters",
    "facility_parameters",
    "axis_parameters",
    "polygon_parameters",
    "site_area_parameters",
)


def _claim_draft_semantic_errors(raw: PlanningClaimDraft) -> list[str]:
    """Validate cross-field combinations before lossy normalization.

    Provider-facing fields remain individually typed so a claim-local repair
    can be requested without rejecting the entire response.  This function is
    the executable cross-field contract for spatial interventions.
    """

    if raw.planning_role != "spatial_intervention":
        return []

    claim_id = _text(raw.claim_id) or "claim"
    category = _text(raw.suggested_category).lower()
    output = _raw_output_kind(raw)
    asset = _text(raw.asset_kind).lower()
    present = [
        field
        for field in _TYPED_PARAMETER_FIELDS
        if getattr(raw, field, None) is not None
    ]
    reasons: list[str] = []

    if category == "action":
        if asset in _LINEAR_ASSETS:
            reasons.append(
                f"asset_kind={asset} requires suggested_category=road, "
                "suggested_output_kind=line, and linear_parameters"
            )
        reasons.append(
            "spatial_intervention cannot use suggested_category=action; "
            "use a spatial category or planning_role=non_spatial_action"
        )
        if output != "action":
            reasons.append(
                "suggested_category=action requires suggested_output_kind=action"
            )
        if asset != "none":
            reasons.append(
                "suggested_category=action requires asset_kind=none"
            )
        if present:
            reasons.append(
                "suggested_category=action requires all typed parameter blocks "
                "to be null"
            )
    elif category == "road":
        if output != "line":
            reasons.append("suggested_category=road requires suggested_output_kind=line")
        if asset == "road":
            required = "road_parameters"
        elif asset in _LINEAR_ASSETS:
            required = "linear_parameters"
        else:
            required = ""
            reasons.append(
                "road spatial_intervention requires asset_kind=road or a "
                "supported linear asset"
            )
        if required and present != [required]:
            reasons.append(
                f"asset_kind={asset} requires exactly {required} and all other "
                "typed parameter blocks must be null"
            )
    else:
        expected_output = (
            next(iter(_SITE_AREA_OUTPUTS))
            if category == "site_area" and output not in _SITE_AREA_OUTPUTS
            else output
        )
        expected_output = {
            "facility": "point",
            "axis": "line",
            "restoration": "polygon",
            "protection": "polygon",
            "zone": "polygon",
        }.get(category, expected_output)
        if output != expected_output:
            reasons.append(
                f"suggested_category={category} requires "
                f"suggested_output_kind={expected_output}"
            )
        allowed_assets = {
            "facility": {"none", "facility"},
            "site_area": {"none"},
            "axis": {"none", "axis"},
            "restoration": {"none"},
            "protection": {"none"},
            "zone": {"none", "land_use"},
        }
        if category in allowed_assets and asset not in allowed_assets[category]:
            reasons.append(
                f"asset_kind={asset} is incompatible with suggested_category={category}"
            )
        required_by_category = {
            "facility": "facility_parameters",
            "axis": "axis_parameters",
            "restoration": "polygon_parameters",
            "protection": "polygon_parameters",
            "zone": "polygon_parameters",
            "site_area": "site_area_parameters",
        }
        required = required_by_category.get(category, "")
        if required and present != [required]:
            reasons.append(
                f"suggested_category={category} requires exactly {required} "
                "and all other typed parameter blocks must be null"
            )

    if not reasons:
        return []
    return [
        f"ERROR[draft_contract_invalid] {claim_id}: "
        + "; ".join(dict.fromkeys(reasons))
    ]


def claim_draft_semantic_errors(
    draft_set: PlanningClaimDraftSet,
) -> list[str]:
    """Return claim-local cross-field contract errors from provider drafts."""

    errors: list[str] = []
    for raw in draft_set.claims:
        errors.extend(_claim_draft_semantic_errors(raw))
    return list(dict.fromkeys(errors))


def _measure_value(
    measure: MeasureDraft | None,
    factors: dict[str, float],
    *,
    claim_id: str,
    field_name: str,
    diagnostics: list[str],
) -> float | None:
    if measure is None or measure.value is None:
        return None
    from app.domain.program.unit_normalization import normalize_unit

    unit = normalize_unit(measure.unit)
    factor = factors.get(unit)
    if factor is None:
        _diagnostic(
            diagnostics,
            "warning",
            "unsupported_measure_unit",
            claim_id,
            f"{field_name} unit {measure.unit!r} is not supported; measure dropped",
        )
        return None
    return float(measure.value) * factor


def _normalized_action(
    value: str,
    *,
    claim_id: str,
    diagnostics: list[str],
    allowed: set[str] | None = None,
) -> str:
    from app.domain.program.unit_normalization import normalize_action

    action = normalize_action(value, allowed=allowed or _ACTION_SET) or "new"
    valid = allowed or _ACTION_SET
    if action not in valid:
        _diagnostic(
            diagnostics,
            "warning",
            "invalid_intervention_action",
            claim_id,
            f"action {action!r} is outside the closed set",
        )
        return "new"
    return action


def _normalize_road_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> RoadPlanningParameters | None:
    source = raw.road_parameters
    if source is None:
        return None
    try:
        road_level = _text(source.road_level)
        return RoadPlanningParameters(
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
                allowed={"preserve", "new", "upgrade", "widen", "harden", "repair"},
            ),
            road_level=road_level,
            length_m=_measure_value(
                source.length,
                _LENGTH_TO_M,
                claim_id=claim_id,
                field_name="length",
                diagnostics=diagnostics,
            ),
            roadbed_width_m=_measure_value(
                source.roadbed_width,
                _LENGTH_TO_M,
                claim_id=claim_id,
                field_name="roadbed_width",
                diagnostics=diagnostics,
            ),
            pavement_width_m=_measure_value(
                source.pavement_width,
                _LENGTH_TO_M,
                claim_id=claim_id,
                field_name="pavement_width",
                diagnostics=diagnostics,
            ),
            alignment_refs=_clean_refs(source.alignment_refs),
            connects=_clean_refs(source.connects),
        )
    except ValueError as exc:
        _diagnostic(
            diagnostics,
            "warning",
            "invalid_road_parameters",
            claim_id,
            f"{exc}; road_parameters dropped",
        )
        return None


def _normalize_linear_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> LinearAssetPlanningParameters | None:
    source = raw.linear_parameters
    if source is None:
        return None
    try:
        return LinearAssetPlanningParameters(
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
                allowed={"preserve", "new", "upgrade", "expand", "repair"},
            ),
            length_m=_measure_value(source.length, _LENGTH_TO_M, claim_id=claim_id, field_name="length", diagnostics=diagnostics),
            diameter_mm=_measure_value(source.diameter, _DIAMETER_TO_MM, claim_id=claim_id, field_name="diameter", diagnostics=diagnostics),
            material=_text(source.material),
            alignment_refs=_clean_refs(source.alignment_refs),
            connects=_clean_refs(source.connects),
        )
    except ValueError as exc:
        _diagnostic(diagnostics, "warning", "invalid_linear_parameters", claim_id, f"{exc}; linear_parameters dropped")
        return None


def _normalize_facility_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> FacilityPlanningParameters | None:
    source = raw.facility_parameters
    if source is None:
        return None
    capacity = source.capacity.value if source.capacity is not None else None
    capacity_unit = source.capacity.unit if source.capacity is not None else ""
    try:
        return FacilityPlanningParameters(
            facility_type=_text(source.facility_type),
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
                allowed={"preserve", "new", "expand", "relocate", "repair"},
            ),
            service_radius_m=_measure_value(
                source.service_radius,
                _LENGTH_TO_M,
                claim_id=claim_id,
                field_name="service_radius",
                diagnostics=diagnostics,
            ),
            capacity=capacity,
            capacity_unit=_text(capacity_unit),
            footprint_area_m2=_measure_value(
                source.footprint_area,
                _AREA_TO_M2,
                claim_id=claim_id,
                field_name="footprint_area",
                diagnostics=diagnostics,
            ),
        )
    except ValueError as exc:
        _diagnostic(diagnostics, "warning", "invalid_facility_parameters", claim_id, f"{exc}; facility_parameters dropped")
        return None


def _normalize_axis_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> AxisPlanningParameters | None:
    source = raw.axis_parameters
    if source is None:
        return None
    try:
        return AxisPlanningParameters(
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
                allowed={"preserve", "new", "upgrade"},
            ),
            axis_type=_text(source.axis_type).lower() or "primary",
            direction=_text(source.direction),
            reference_features=_clean_refs(source.reference_features),
            connects=_clean_refs(source.connects),
            corridor_width_m=_measure_value(
                source.corridor_width,
                _LENGTH_TO_M,
                claim_id=claim_id,
                field_name="corridor_width",
                diagnostics=diagnostics,
            ),
        )
    except ValueError as exc:
        _diagnostic(diagnostics, "warning", "invalid_axis_parameters", claim_id, f"{exc}; axis_parameters dropped")
        return None


def _normalize_polygon_parameters(
    raw: PlanningClaimDraft,
    category: str,
    claim_id: str,
    diagnostics: list[str],
) -> tuple[PolygonPlanningParameters | None, tuple[float, float] | None]:
    source = raw.polygon_parameters
    role = _text(source.materialization_role).lower() if source is not None else ""
    if category == "protection":
        role = "protection_overlay"
    elif category == "restoration":
        role = "restoration_overlay"
    if not role:
        return None, None
    allowed_roles = {
        "site_area": {"site_footprint"},
        "zone": {
            "land_use_assignment",
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
            "site_footprint",
        },
        "protection": {"protection_overlay"},
        "restoration": {"restoration_overlay"},
    }
    if role not in allowed_roles.get(category, set()):
        # Structure is valid; the role is auto-corrected to the category's
        # allowed role instead of dropping the polygon parameters.
        _diagnostic(
            diagnostics,
            "warning",
            "materialization_role_mismatch",
            claim_id,
            f"role {role!r} is incompatible with category {category!r}",
        )
        role = next(iter(allowed_roles.get(category, set())), "site_footprint")
    area_range: tuple[float, float] | None = None
    if (
        source is not None
        and source.area_range is not None
        and role != "functional_overlay"
    ):
        area = source.area_range
        unit = _text(area.unit).lower()
        factor = _AREA_TO_HA.get(unit)
        if factor is None and unit in _COUNT_AS_AREA_UNITS:
            # 计数单位（处/个/座/点…）作为 area_range：语义上是"数量"而非面积，
            # 不是可换算的面积。丢弃面积约束（功能/点状项目本就不需要地块面积），
            # 记 warning 而非 error，避免整个 program 被结构性阻断。
            _diagnostic(
                diagnostics,
                "warning",
                "count_unit_as_area_dropped",
                claim_id,
                f"area_range unit {area.unit!r} is a count, not an area; area constraint dropped",
            )
            source.area_range = None
            area = None
        elif factor is None:
            _diagnostic(
                diagnostics,
                "warning",
                "unsupported_area_unit",
                claim_id,
                f"area_range unit {area.unit!r} is not supported; area constraint dropped",
            )
        elif area.minimum is None or area.maximum is None:
            _diagnostic(
                diagnostics,
                "warning",
                "incomplete_area_range",
                claim_id,
                "area_range missing minimum or maximum; area constraint dropped",
            )
        else:
            minimum = float(area.minimum) * factor
            maximum = float(area.maximum) * factor
            if minimum <= 0 or maximum < minimum:
                _diagnostic(
                    diagnostics,
                    "warning",
                    "invalid_area_range",
                    claim_id,
                    f"area range is invalid: {minimum}-{maximum}ha; area constraint dropped",
                )
            else:
                area_range = (minimum, maximum)
    elif source is not None and source.area_range is not None:
        _diagnostic(
            diagnostics,
            "info",
            "functional_overlay_area_non_authoritative",
            claim_id,
            "functional overlay area is retained in source evidence but is not an allocation target",
        )
    try:
        parameters = PolygonPlanningParameters(
            materialization_role=role,
            planning_zone=_text(source.planning_zone) if source is not None else "",
            land_use=_text(source.land_use) if source is not None else "",
        )
    except ValueError as exc:
        _diagnostic(diagnostics, "warning", "invalid_polygon_parameters", claim_id, f"{exc}; polygon_parameters dropped")
        return None, area_range
    return parameters, area_range


def _normalize_site_area_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> SiteAreaPlanningParameters | None:
    source = raw.site_area_parameters
    if source is None:
        return None
    capacity = source.capacity.value if source.capacity is not None else None
    capacity_unit = source.capacity.unit if source.capacity is not None else ""
    try:
        return SiteAreaPlanningParameters(
            site_type=_text(source.site_type),
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
            ),
            capacity=capacity,
            capacity_unit=_text(capacity_unit),
            footprint_area_m2=_measure_value(
                source.footprint_area,
                _AREA_TO_M2,
                claim_id=claim_id,
                field_name="footprint_area",
                diagnostics=diagnostics,
            ),
        )
    except ValueError as exc:
        _diagnostic(diagnostics, "warning", "invalid_site_area_parameters", claim_id, f"{exc}; site_area_parameters dropped")
        return None


def normalize_claim_draft_set(
    draft_set: PlanningClaimDraftSet,
    *,
    dimension_key: str = "",
) -> PlanningClaimSet:
    """Convert provider drafts into the sole strict L3 claim contract.

    A malformed individual claim is quarantined as a diagnostic instead of
    terminating the entire dimension.  No geometry, classification, parcel
    binding, or executable target is created here.
    """

    resolved_dimension = dimension_key or _text(draft_set.dimension_key)
    diagnostics = [
        note
        if str(note).startswith(("ERROR[", "WARNING[", "INFO["))
        else f"INFO[provider_note] {resolved_dimension}: {note}"
        for note in draft_set.diagnostics
    ]
    claims: list[PlanningClaim] = []
    for raw in draft_set.claims:
        claim_id = _text(raw.claim_id)
        statement = _text(raw.statement)
        if not claim_id or not statement:
            _diagnostic(
                diagnostics,
                "warning",
                "missing_claim_identity",
                claim_id or "claim",
                "missing claim_id or statement; omitted",
            )
            continue
        draft_contract_errors = _claim_draft_semantic_errors(raw)
        if draft_contract_errors:
            diagnostics.extend(draft_contract_errors)
            continue
        category = _normalize_category(raw, diagnostics)
        raw_asset_kind = _text(raw.asset_kind).lower()
        raw_output = _raw_output_kind(raw)
        if (
            category == "facility"
            and raw_output == "line"
            and raw_asset_kind in _LINEAR_ASSETS
        ):
            # Providers occasionally follow the semantic asset enum but put
            # a utility line under ``facility``.  Preserve the declared
            # linear asset and let GROUND resolve its corridor; do not turn a
            # pipeline into a point merely because the typed block was
            # omitted.  No geometry or measurements are synthesized here.
            _diagnostic(
                diagnostics,
                "warning",
                "linear_category_repaired",
                claim_id,
                f"{category}/{raw_output} with asset_kind {raw_asset_kind!r} normalized to road/line",
            )
            category = "road"
        output = _normalize_output(raw, category, diagnostics)
        asset_kind = _normalize_asset_kind(raw, category, output, diagnostics)
        if category == "road" and asset_kind == "none":
            _diagnostic(
                diagnostics,
                "error",
                "missing_asset_kind",
                claim_id,
                "line claim must select an asset_kind from the closed set",
            )
        phase = _text(raw.implementation_phase).lower()
        if phase not in {"short", "medium", "long"}:
            _diagnostic(
                diagnostics,
                "warning",
                "phase_normalized",
                claim_id,
                f"invalid implementation_phase {phase!r}; normalized to 'short'",
            )
            phase = "short"
        uncertainty = _text(raw.uncertainty)
        if raw.quantity is not None and not _text(raw.quantity_unit):
            _diagnostic(
                diagnostics,
                "warning",
                "unitless_quantity",
                claim_id,
                "missing quantity_unit; retained as unitless quantity",
            )
        if category == "action" and output == "action" and not uncertainty:
            uncertainty = "non-spatial action; no GIS placement is implied"
        road_parameters = (
            _normalize_road_parameters(raw, claim_id, diagnostics)
            if category == "road" and asset_kind == "road"
            else None
        )
        linear_parameters = (
            _normalize_linear_parameters(raw, claim_id, diagnostics)
            if category == "road" and asset_kind not in {"none", "road"}
            else None
        )
        if category == "road" and asset_kind not in {"none", "road"} and linear_parameters is None:
            # Keep an incomplete utility claim auditable and routable.  The
            # source statement/location hints remain the only semantic input;
            # GROUND must still find evidence before any spatial output.
            linear_parameters = LinearAssetPlanningParameters(
                action=_normalized_action(
                    raw.intervention_action,
                    claim_id=claim_id,
                    diagnostics=diagnostics,
                    allowed={"preserve", "new", "upgrade", "expand", "repair"},
                )
            )
            _diagnostic(
                diagnostics,
                "warning",
                "linear_parameters_defaulted_for_grounding",
                claim_id,
                "linear asset had no typed parameters; preserved as an evidence-dependent corridor",
            )
        facility_parameters = (
            _normalize_facility_parameters(raw, claim_id, diagnostics)
            if category == "facility"
            else None
        )
        axis_parameters = (
            _normalize_axis_parameters(raw, claim_id, diagnostics)
            if category == "axis"
            else None
        )
        if category in {"site_area", "zone", "protection", "restoration"}:
            polygon_parameters, area_range_ha = _normalize_polygon_parameters(
                raw,
                category,
                claim_id,
                diagnostics,
            )
        else:
            polygon_parameters, area_range_ha = None, None
        if category == "zone" and polygon_parameters is None:
            # A functional overlay has no authoritative parcel assignment or
            # area claim.  It is the safe typed representation for a zone
            # whose provider response omitted polygon_parameters; GROUND and
            # VALIDATE remain responsible for evidence and geometry.
            polygon_parameters = PolygonPlanningParameters(
                materialization_role="functional_overlay"
            )
            _diagnostic(
                diagnostics,
                "warning",
                "polygon_parameters_defaulted_for_grounding",
                claim_id,
                "zone omitted polygon_parameters; preserved as an evidence-dependent functional overlay",
            )
        site_area_parameters = (
            _normalize_site_area_parameters(raw, claim_id, diagnostics)
            if category == "site_area"
            else None
        )
        action_source = raw.intervention_action
        if road_parameters is not None:
            action_source = road_parameters.action
        elif linear_parameters is not None:
            action_source = linear_parameters.action
        elif facility_parameters is not None:
            action_source = facility_parameters.action
        elif axis_parameters is not None:
            action_source = axis_parameters.action
        elif raw.site_area_parameters is not None:
            action_source = raw.site_area_parameters.action
        intervention_action = _normalized_action(
            action_source,
            claim_id=claim_id,
            diagnostics=diagnostics,
        )
        try:
            claim = PlanningClaim(
                claim_id=claim_id,
                dimension_key=resolved_dimension or _text(raw.dimension_key),
                statement=statement,
                planning_role=raw.planning_role,
                project_package_ref=_text(raw.project_package_ref),
                affected_population=raw.affected_population,
                affected_parcel_refs=_clean_refs(raw.affected_parcel_refs),
                suggested_category=category,
                suggested_output_kind=output,
                asset_kind=asset_kind,
                suggested_interventions=_clean_refs(raw.suggested_interventions),
                quantity=raw.quantity,
                quantity_unit=_text(raw.quantity_unit),
                area_range_ha=area_range_ha,
                intervention_action=intervention_action,
                materialization_role=(
                    polygon_parameters.materialization_role
                    if polygon_parameters is not None
                    else (
                        "site_footprint"
                        if category == "site_area" and output in {"parcel", "polygon"}
                        else None
                    )
                ),
                road_parameters=road_parameters,
                linear_parameters=linear_parameters,
                facility_parameters=facility_parameters,
                axis_parameters=axis_parameters,
                polygon_parameters=polygon_parameters,
                site_area_parameters=site_area_parameters,
                implementation_phase=phase,
                location_hints=_clean_refs(raw.location_hints),
                constraint_refs=_clean_refs(raw.constraint_refs),
                objective_refs=_clean_refs(raw.objective_refs),
                evidence_refs=_clean_refs(raw.evidence_refs),
                source_fact_refs=_clean_refs(raw.source_fact_refs),
                source_refs=_clean_refs(raw.source_refs),
                spatial_requirements=raw.spatial_requirements,
                confidence=raw.confidence,
                uncertainty=uncertainty,
            )
        except ValidationError as exc:
            _diagnostic(
                diagnostics,
                "error",
                "claim_contract_invalid",
                claim_id,
                f"strict claim contract rejected; claim quarantined: {exc}",
            )
            continue
        claims.append(claim)
    return PlanningClaimSet(
        schema_version="2.0",
        dimension_key=resolved_dimension,
        claims=claims,
        diagnostics=diagnostics,
    )


def claim_set_semantic_errors(claim_set: PlanningClaimSet) -> list[str]:
    """Return source-compilation errors that should be retried in this L3 worker.

    This validator checks object semantics only.  It never requires BSMs,
    coordinates, geometry, or a successful place binding; those belong to
    GROUND.  Evidence-backed uncertainty may therefore remain explicit.
    """

    errors = [
        str(item)
        for item in claim_set.diagnostics
        if str(item).startswith("ERROR[")
    ]
    # L3 is preference-level planning: it supplies the structured intent and a
    # rough location preference (location_hints / statement).  Precise spatial
    # evidence (road corridor alignment, axis direction, exact widths, area
    # ranges) is GROUND's job to resolve from location hints + KG topology, so
    # those are NOT compile errors here.  Only the structural contract matters:
    # the parameter object must exist and carry its minimum typed fields.
    for claim in claim_set.claims:
        prefix = f"{claim.claim_id}:"
        if claim.suggested_category == "road":
            if claim.asset_kind == "road":
                if claim.road_parameters is None:
                    errors.append(f"{prefix} road_parameters are required for road asset_kind")
            elif claim.asset_kind not in {
                "water_supply", "sewer", "stormwater", "power", "communication",
                "drainage_channel", "revetment",
            }:
                errors.append(f"{prefix} asset_kind must be a supported closed-set linear asset")
            elif claim.linear_parameters is None:
                errors.append(f"{prefix} linear_parameters are required for {claim.asset_kind}")
        elif claim.suggested_category == "facility":
            if claim.facility_parameters is None:
                errors.append(f"{prefix} facility_parameters are required")
            elif not claim.facility_parameters.facility_type:
                errors.append(f"{prefix} facility_type is required")
        elif claim.suggested_category == "axis":
            if claim.axis_parameters is None:
                errors.append(f"{prefix} axis_parameters are required")
        elif claim.suggested_category == "zone":
            if claim.polygon_parameters is None:
                errors.append(f"{prefix} polygon_parameters are required for zone")
        elif claim.suggested_category in {"protection", "restoration"}:
            if claim.polygon_parameters is None:
                errors.append(f"{prefix} overlay materialization parameters are required")
    return list(dict.fromkeys(errors))


def semantic_error_claim_ids(errors: list[str]) -> list[str]:
    """Extract only claim ids named by deterministic compiler feedback."""
    ids: list[str] = []
    for error in errors:
        text = str(error or "")
        if "] " in text:
            text = text.split("] ", 1)[1]
        claim_id = text.split(":", 1)[0].strip()
        if claim_id and claim_id not in {"claim", "program"}:
            ids.append(claim_id)
    return list(dict.fromkeys(ids))


def merge_repaired_claim_drafts(
    original: PlanningClaimDraftSet,
    repaired: PlanningClaimDraftSet,
    target_claim_ids: list[str],
) -> PlanningClaimDraftSet:
    """Replace only validator-rejected drafts; preserve all accepted claims."""
    target_ids = set(target_claim_ids)
    repaired_by_id = {
        str(item.claim_id): item
        for item in repaired.claims
        if str(item.claim_id) in target_ids
    }
    merged = [
        repaired_by_id.get(str(item.claim_id), item)
        for item in original.claims
    ]
    return original.model_copy(
        update={
            "schema_version": "2.0",
            "claims": merged,
            "diagnostics": list(repaired.diagnostics),
        },
        deep=True,
    )


__all__ = [
    "L3ClaimOutput",
    "L3ReportOutput",
    "PlanningClaimDraft",
    "PlanningClaimDraftSet",
    "claim_draft_semantic_errors",
    "claim_set_semantic_errors",
    "merge_repaired_claim_drafts",
    "normalize_claim_draft_set",
    "semantic_error_claim_ids",
]
