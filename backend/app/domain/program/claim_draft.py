"""Provider-facing planning claim drafts and their domain normalization.

The LLM is allowed to be incomplete or semantically imprecise at this
boundary.  It is not allowed to create an executable target.  This module is
the only place that converts provider drafts into the strict claim contract.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.contracts.program import PlanningClaim, PlanningClaimSet


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
    suggested_category: str = "action"
    suggested_output_kind: str = "action"
    suggested_interventions: list[str] = Field(default_factory=list)
    quantity: float | None = None
    quantity_unit: str | None = None
    implementation_phase: str = "short"
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


class PlanningClaimDraftSet(BaseModel):
    """Provider response before domain validation."""

    schema_version: str = "1.0"
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
    diagnostics.append(
        f"{raw.claim_id or 'claim'}: unsupported category {category!r}; kept as action"
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
        diagnostics.append(
            f"{raw.claim_id or 'claim'}: project output {output!r} is not executable; deferred as action"
        )
        return "action"
    expected = _ALLOWED_OUTPUTS[category]
    if output != expected:
        diagnostics.append(
            f"{raw.claim_id or 'claim'}: {category} output {output!r} normalized to {expected!r}"
        )
    return expected


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
    diagnostics = list(draft_set.diagnostics)
    claims: list[PlanningClaim] = []
    for raw in draft_set.claims:
        claim_id = _text(raw.claim_id)
        statement = _text(raw.statement)
        if not claim_id or not statement:
            diagnostics.append(
                f"{claim_id or 'claim'}: missing claim_id or statement; omitted"
            )
            continue
        category = _normalize_category(raw, diagnostics)
        output = _normalize_output(raw, category, diagnostics)
        phase = _text(raw.implementation_phase).lower()
        if phase not in {"short", "medium", "long"}:
            diagnostics.append(f"{claim_id}: invalid implementation_phase {phase!r}; normalized to 'short'")
            phase = "short"
        uncertainty = _text(raw.uncertainty)
        if raw.quantity is not None and not _text(raw.quantity_unit):
            diagnostics.append(f"{claim_id}: missing quantity_unit; retained as unitless quantity")
        if category == "action" and output == "action" and not uncertainty:
            uncertainty = "non-spatial action; no GIS placement is implied"
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
        schema_version="1.0",
        dimension_key=resolved_dimension,
        claims=claims,
        diagnostics=diagnostics,
    )


__all__ = [
    "PlanningClaimDraft",
    "PlanningClaimDraftSet",
    "normalize_claim_draft_set",
]
