"""Provider-facing planning claim drafts and their domain normalization.

The LLM is allowed to be incomplete or semantically imprecise at this
boundary.  It is not allowed to create an executable target.  This module is
the only place that converts provider drafts into the strict claim contract.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, field_validator

from app.contracts.program import PlanningClaim, PlanningClaimSet
from app.contracts.domain.planning_semantics import (
    AxisPlanningParameters,
    FacilityPlanningParameters,
    PolygonPlanningParameters,
    ProjectPlanningParameters,
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
    "project",
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
        "project_footprint",
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


class ProjectPlanningParametersDraft(BaseModel):
    project_type: str = ""
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
    affected_population: float | None = None
    affected_parcel_refs: list[str] = Field(default_factory=list)
    suggested_category: PlanningCategoryDraft = "action"
    suggested_output_kind: PlanningOutputDraft = "action"
    suggested_interventions: list[str] = Field(default_factory=list)
    quantity: float | None = None
    quantity_unit: str | None = None
    intervention_action: PlanningActionDraft = "new"
    road_parameters: RoadPlanningParametersDraft | None = None
    facility_parameters: FacilityPlanningParametersDraft | None = None
    axis_parameters: AxisPlanningParametersDraft | None = None
    polygon_parameters: PolygonPlanningParametersDraft | None = None
    project_parameters: ProjectPlanningParametersDraft | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    location_hints: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    objective_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    uncertainty: str = ""

    @field_validator(
        "affected_parcel_refs",
        "suggested_interventions",
        "location_hints",
        "constraint_refs",
        "objective_refs",
        "evidence_refs",
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
        "project_parameters",
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


class L3DimensionOutput(BaseModel):
    """Dual-response L3 output: narrative report body + structured claims.

    ``report_body`` is the human-facing deliverable (fed into the statutory
    .docx text); ``claims`` is the machine-consumed structured data (compiled
    by ``normalize_claim_draft_set`` into ``PlanningClaimSet``).  The provider
    returns both in one function-calling response so the report body is never
    dropped in favor of the machine contract.
    """

    report_body: str = ""
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
    "project",
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
_PROJECT_OUTPUTS = {"parcel", "polygon", "point", "action"}
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


def _normalize_output(
    raw: PlanningClaimDraft,
    category: str,
    diagnostics: list[str],
) -> str:
    output = _OUTPUT_ALIASES.get(_text(raw.suggested_output_kind).lower(), _text(raw.suggested_output_kind).lower())
    if category == "project":
        if output in _PROJECT_OUTPUTS:
            return output
        _diagnostic(
            diagnostics,
            "warning",
            "invalid_project_output",
            raw.claim_id or "claim",
            f"project output {output!r} is not executable; deferred as action",
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
            "error",
            "unsupported_measure_unit",
            claim_id,
            f"{field_name} unit {measure.unit!r} is not supported",
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
        return RoadPlanningParameters(
            action=_normalized_action(
                source.action,
                claim_id=claim_id,
                diagnostics=diagnostics,
                allowed={"preserve", "new", "upgrade", "widen", "harden", "repair"},
            ),
            road_level=_text(source.road_level),
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
            "error",
            "invalid_road_parameters",
            claim_id,
            str(exc),
        )
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
        _diagnostic(diagnostics, "error", "invalid_facility_parameters", claim_id, str(exc))
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
        _diagnostic(diagnostics, "error", "invalid_axis_parameters", claim_id, str(exc))
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
        "project": {"project_footprint"},
        "zone": {
            "land_use_assignment",
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
            "project_footprint",
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
        role = next(iter(allowed_roles.get(category, set())), "project_footprint")
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
                "error",
                "unsupported_area_unit",
                claim_id,
                f"area_range unit {area.unit!r} is not supported",
            )
        elif area.minimum is None or area.maximum is None:
            _diagnostic(
                diagnostics,
                "error",
                "incomplete_area_range",
                claim_id,
                "area_range requires minimum and maximum",
            )
        else:
            minimum = float(area.minimum) * factor
            maximum = float(area.maximum) * factor
            if minimum <= 0 or maximum < minimum:
                _diagnostic(
                    diagnostics,
                    "error",
                    "invalid_area_range",
                    claim_id,
                    f"area range is invalid: {minimum}-{maximum}ha",
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
        _diagnostic(diagnostics, "error", "invalid_polygon_parameters", claim_id, str(exc))
        return None, area_range
    return parameters, area_range


def _normalize_project_parameters(
    raw: PlanningClaimDraft,
    claim_id: str,
    diagnostics: list[str],
) -> ProjectPlanningParameters | None:
    source = raw.project_parameters
    if source is None:
        return None
    capacity = source.capacity.value if source.capacity is not None else None
    capacity_unit = source.capacity.unit if source.capacity is not None else ""
    try:
        return ProjectPlanningParameters(
            project_type=_text(source.project_type),
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
        _diagnostic(diagnostics, "error", "invalid_project_parameters", claim_id, str(exc))
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
                "error",
                "missing_claim_identity",
                claim_id or "claim",
                "missing claim_id or statement; omitted",
            )
            continue
        category = _normalize_category(raw, diagnostics)
        output = _normalize_output(raw, category, diagnostics)
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
            if category == "road"
            else None
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
        if category in {"project", "zone", "protection", "restoration"}:
            polygon_parameters, area_range_ha = _normalize_polygon_parameters(
                raw,
                category,
                claim_id,
                diagnostics,
            )
        else:
            polygon_parameters, area_range_ha = None, None
        project_parameters = (
            _normalize_project_parameters(raw, claim_id, diagnostics)
            if category == "project"
            else None
        )
        action_source = raw.intervention_action
        if road_parameters is not None:
            action_source = road_parameters.action
        elif facility_parameters is not None:
            action_source = facility_parameters.action
        elif axis_parameters is not None:
            action_source = axis_parameters.action
        elif raw.project_parameters is not None:
            action_source = raw.project_parameters.action
        intervention_action = _normalized_action(
            action_source,
            claim_id=claim_id,
            diagnostics=diagnostics,
        )
        claims.append(
            PlanningClaim(
                claim_id=claim_id,
                dimension_key=resolved_dimension or _text(raw.dimension_key),
                statement=statement,
                affected_population=raw.affected_population,
                affected_parcel_refs=_clean_refs(raw.affected_parcel_refs),
                suggested_category=category,
                suggested_output_kind=output,
                suggested_interventions=_clean_refs(raw.suggested_interventions),
                quantity=raw.quantity,
                quantity_unit=_text(raw.quantity_unit),
                area_range_ha=area_range_ha,
                intervention_action=intervention_action,
                materialization_role=(
                    polygon_parameters.materialization_role
                    if polygon_parameters is not None
                    else (
                        "project_footprint"
                        if category == "project" and output in {"parcel", "polygon"}
                        else None
                    )
                ),
                road_parameters=road_parameters,
                facility_parameters=facility_parameters,
                axis_parameters=axis_parameters,
                polygon_parameters=polygon_parameters,
                project_parameters=project_parameters,
                implementation_phase=phase,
                location_hints=_clean_refs(raw.location_hints),
                constraint_refs=_clean_refs(raw.constraint_refs),
                objective_refs=_clean_refs(raw.objective_refs),
                evidence_refs=_clean_refs(raw.evidence_refs),
                source_refs=_clean_refs(raw.source_refs),
                confidence=raw.confidence,
                uncertainty=uncertainty,
            )
        )
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
            if claim.road_parameters is None:
                errors.append(f"{prefix} road_parameters are required")
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
    "L3DimensionOutput",
    "PlanningClaimDraft",
    "PlanningClaimDraftSet",
    "claim_set_semantic_errors",
    "merge_repaired_claim_drafts",
    "normalize_claim_draft_set",
    "semantic_error_claim_ids",
]
