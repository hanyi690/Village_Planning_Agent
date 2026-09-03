"""Stable projections between report/KG evidence and authoritative L1 facts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from app.contracts.l1.l1_contracts import (
    L1Fact,
    LocationMention,
    LocationMentionDraft,
    LocationScopeMention,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _refs(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def stable_l1_fact_id(
    *,
    fact_kind: str,
    dimension_key: str,
    statement: str,
    confidence: float = 0.0,
    source_refs: Iterable[Any],
    source_span: str = "",
    source_span_refs: Iterable[Any] = (),
    subject_scope: str = "",
) -> str:
    payload = {
        "fact_kind": _text(fact_kind),
        "dimension_key": _text(dimension_key),
        "statement": _text(statement),
        "source_refs": _refs(source_refs),
        "source_span": _text(source_span),
        "subject_scope": _text(subject_scope),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"l1:fact:{digest}"


def make_l1_fact(
    *,
    statement: str,
    confidence: float = 0.0,
    fact_kind: str,
    dimension_key: str = "",
    subject_scope: str = "",
    semantic_type: str = "",
    attributes: dict[str, Any] | None = None,
    value: str | int | float | None = None,
    unit: str = "",
    counting_basis: str = "",
    source_refs: Iterable[Any] = (),
    evidence_refs: Iterable[Any] = (),
    source_span: str = "",
    source_span_refs: Iterable[Any] = (),
    source_snapshot_ref: str = "",
    source_feature_ids: Iterable[Any] = (),
    derivation: str = "",
    inference_level: str = "",
    uncertainty: str = "",
    status: str = "",
) -> L1Fact | None:
    statement = _text(statement)
    refs = _refs(source_refs)
    if not statement or not refs:
        return None
    default_level = {
        "derived_metric": "derived",
        "kg_canonical_fact": "inferred",
    }.get(_text(fact_kind), "observed")
    level = _text(inference_level) or default_level
    allowed_levels = {"observed", "derived", "inferred", "conflicted", "pending"}
    if level not in allowed_levels:
        level = default_level
    fact_status = _text(status) or level
    if fact_status not in allowed_levels:
        fact_status = level
    fact_id = stable_l1_fact_id(
        fact_kind=fact_kind,
        dimension_key=dimension_key,
        statement=statement,
        source_refs=refs,
        source_span=source_span,
        subject_scope=subject_scope,
    )
    return L1Fact(
        fact_id=fact_id,
        statement=statement,
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        fact_kind=fact_kind,
        inference_level=level,
        uncertainty=_text(uncertainty),
        status=fact_status,
        dimension_key=_text(dimension_key),
        subject_scope=_text(subject_scope),
        semantic_type=_text(semantic_type),
        attributes={
            _text(key): _text(value)
            for key, value in (attributes or {}).items()
            if _text(key) and _text(value)
        },
        value=value,
        unit=_text(unit),
        counting_basis=_text(counting_basis),
        source_refs=refs,
        evidence_refs=_refs(evidence_refs),
        source_span=_text(source_span),
        source_span_refs=_refs(source_span_refs),
        source_snapshot_ref=_text(source_snapshot_ref),
        source_feature_ids=_refs(source_feature_ids),
        derivation=_text(derivation),
    )


def planning_observation_to_l1_fact(
    observation: Any,
    *,
    dimension_key: str,
    source_snapshot_ref: str = "",
) -> L1Fact | None:
    """Project one admitted typed observation without passing through prose."""

    payload = observation.model_dump(mode="json")
    fact_type = _text(payload.get("fact_type"))
    semantic_type = _text(payload.get("semantic_type")) or fact_type
    subject_scope = _text(
        payload.get("scope")
        or payload.get("applies_to_scope")
        or payload.get("name")
        or payload.get("subject")
        or payload.get("metric")
        or payload.get("demand_type")
        or payload.get("constraint_type")
        or payload.get("subject_ref")
    )
    if fact_type == "spatial_entity":
        statement = f"{payload.get('entity_type', '')}: {payload.get('name', '')}"
        attributes = {
            "entity_type": payload.get("entity_type", ""),
            "name": payload.get("name", ""),
            "scale": payload.get("scale", ""),
            "place_names": payload.get("locator", {}).get("place_names", []),
            "relation": payload.get("locator", {}).get("relation", ""),
        }
    elif fact_type == "spatial_relation":
        statement = (
            f"{payload.get('subject_ref', '')} {payload.get('predicate', '')} "
            f"{payload.get('object_ref', '')}"
        )
        attributes = {
            key: payload.get(key, "")
            for key in ("subject_ref", "predicate", "object_ref")
        }
    else:
        statement = _text(payload.get("description"))
        if not statement:
            statement = "; ".join(
                f"{key}={payload[key]}"
                for key in (
                    "semantic_type", "metric", "demand_type", "constraint_type",
                    "subject", "scope", "applies_to_scope", "value", "unit",
                )
                if _text(payload.get(key))
            )
        attributes = {
            key: payload.get(key, "")
            for key in (
                "fact_type", "semantic_type", "metric", "demand_type",
                "constraint_type", "subject", "scope", "applies_to_scope",
                "beneficiary", "strength", "spatial_requirement",
            )
            if _text(payload.get(key))
        }
    source_refs = list(payload.get("source_refs") or [])
    if source_snapshot_ref:
        source_refs.append(source_snapshot_ref)
    segment_ids = list(payload.get("source_segment_ids") or [])
    source_refs.extend(f"segment:{value}" for value in segment_ids)
    status = _text(payload.get("status"))
    status_map = {
        "confirmed": ("observed", "observed"),
        "uncertain": ("pending", "pending"),
        "source_exhausted": ("pending", "pending"),
        "conflict": ("conflicted", "conflicted"),
    }
    fact_status, inference_level = status_map.get(status, ("pending", "pending"))
    return make_l1_fact(
        statement=statement,
        fact_kind=(
            "spatial_observation"
            if fact_type in {"spatial_entity", "spatial_relation"}
            else "document_observation"
        ),
        confidence=payload.get("confidence") or 0.0,
        dimension_key=dimension_key,
        subject_scope=subject_scope,
        semantic_type=semantic_type,
        attributes=attributes,
        value=payload.get("value"),
        unit=_text(payload.get("unit")),
        counting_basis=_text(payload.get("counting_basis")),
        source_refs=source_refs,
        evidence_refs=[
            _text(payload.get("observation_id")),
            *[f"segment:{value}" for value in segment_ids],
        ],
        source_span=_text(payload.get("source_quote")),
        source_span_refs=[f"segment:{value}" for value in segment_ids],
        source_snapshot_ref=source_snapshot_ref,
        source_feature_ids=(
            payload.get("source_feature_ids") or []
        ) + (
            payload.get("locator", {}).get("source_feature_ids", [])
            if isinstance(payload.get("locator"), dict)
            else []
        ),
        status=fact_status,
        inference_level=inference_level,
        uncertainty=("provider marked observation uncertain" if status == "uncertain" else ""),
    )


def planning_observation_to_location_mentions(
    observation: Any,
    *,
    dimension_key: str,
    source_report_ref: str,
) -> list[LocationMention]:
    """Project typed spatial work items; no canonical entity or geometry is added."""

    mentions: list[LocationMention] = []
    for draft in getattr(observation, "spatial_mentions", ()) or ():
        if not isinstance(draft, LocationMentionDraft):
            draft = LocationMentionDraft.model_validate(draft)
        provenance = draft.provenance
        source_refs = _refs([
            *provenance.source_refs,
            *(getattr(observation, "source_refs", ()) or ()),
        ])
        source_segment_ids = _refs([
            *provenance.source_segment_ids,
            *(getattr(observation, "source_segment_ids", ()) or ()),
        ])
        source_quote = _text(
            provenance.source_quote or getattr(observation, "source_quote", "")
        )
        source_span_refs = [f"segment:{value}" for value in source_segment_ids]
        scopes = [
            scope
            if isinstance(scope, LocationScopeMention)
            else LocationScopeMention.model_validate(scope)
            for scope in draft.scope_mentions
        ]
        mentions.append(LocationMention(
            mention_kind=draft.mention_kind,
            mention=draft.mention or draft.normalized_name or draft.target_name,
            normalized_name=draft.normalized_name or draft.mention or draft.target_name,
            role=draft.role,
            target_name=draft.target_name,
            aliases=list(draft.aliases),
            relation=draft.relation,
            related_mentions=list(draft.related_mentions),
            scopes=scopes,
            instance_label=draft.instance_label,
            instance_count=draft.instance_count,
            resolution_state=draft.resolution_state,
            provenance=provenance,
            source_report_ref=source_report_ref,
            dimension_key=dimension_key,
            source_span=source_quote,
            source_span_refs=source_span_refs,
            evidence_refs=source_refs,
            source_feature_ids=list(draft.source_feature_ids),
            confidence=getattr(observation, "confidence", 0.0) or 0.0,
        ))
    return mentions


def evidence_fact_to_l1_fact(
    fact: Any,
    *,
    dimension_key: str = "",
    snapshot_ref: str = "",
    spatial_only: bool = False,
) -> L1Fact | None:
    fields = dict(getattr(fact, "fields", None) or {})
    source_kind = _text(fields.get("source_kind")).casefold()
    if source_kind in {"kg", "kg_canonical", "canonical_kg"}:
        fact_kind = "kg_canonical_fact"
    elif source_kind in {
        "gis", "gis_layer", "data_resource_catalog",
    }:
        fact_kind = "gis_observation"
    else:
        fact_kind = "document_observation"
    if spatial_only and source_kind not in {
        "kg", "kg_canonical", "canonical_kg",
        "gis", "gis_layer",
        "data_resource_catalog",
    }:
        return None
    refs = [
        *_refs(getattr(fact, "source_refs", None) or []),
        _text(getattr(fact, "source_locator", "")),
    ]
    feature_ids: list[str] = []
    # KG typed-count facts keep a bounded source-feature sample in fields;
    # retain those IDs when promoting the fact into L1 so the lineage gate
    # can distinguish a traceable aggregate from an unverified count.
    for key in ("source_feature_id", "source_feature_ids", "source_feature_sample"):
        value = fields.get(key)
        if isinstance(value, (list, tuple, set)):
            feature_ids.extend(value)
        elif value:
            feature_ids.extend(re.split(r"[,;]", str(value)))
    source_snapshot = _text(
        fields.get("source_snapshot_ref")
        or snapshot_ref
    )
    return make_l1_fact(
        statement=_text(getattr(fact, "statement", "")),
        confidence=getattr(fact, "confidence", 0.0),
        fact_kind=fact_kind,
        dimension_key=dimension_key or _text(fields.get("dimension_key")),
        subject_scope=_text(fields.get("subject_scope") or fields.get("entity_scope")),
        semantic_type=_text(fields.get("semantic_type") or getattr(fact, "fact_type", "")),
        attributes=fields,
        value=fields.get("value"),
        unit=_text(fields.get("unit")),
        counting_basis=_text(fields.get("counting_basis")),
        source_refs=refs,
        evidence_refs=[
            _text(getattr(fact, "fact_id", "")),
            *_refs(getattr(fact, "related_fact_refs", None) or []),
        ],
        source_span=_text(getattr(fact, "evidence_span", "")),
        source_snapshot_ref=source_snapshot,
        source_feature_ids=feature_ids,
        derivation=_text(fields.get("derivation")),
        inference_level=(
            "inferred"
            if source_kind in {
                "kg", "kg_canonical", "canonical_kg",
                "data_resource_catalog",
            }
            else "observed"
        ),
    )


__all__ = [
    "evidence_fact_to_l1_fact",
    "make_l1_fact",
    "planning_observation_to_l1_fact",
    "planning_observation_to_location_mentions",
    "stable_l1_fact_id",
]
