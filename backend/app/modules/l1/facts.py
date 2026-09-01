"""Stable projections between report/KG evidence and authoritative L1 facts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from app.contracts.l1.l1_contracts import L1Fact, LocationMention


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
        source_snapshot_ref=_text(source_snapshot_ref),
        source_feature_ids=_refs(source_feature_ids),
        derivation=_text(derivation),
    )


def location_mention_to_l1_fact(
    fact: LocationMention,
    *,
    snapshot_ref: str = "",
) -> L1Fact | None:
    mention = _text(fact.mention) or _text(fact.normalized_name)
    role = _text(fact.role) or "unknown"
    statement = f"L1空间事实：{mention}（角色={role}）"
    if _text(fact.spatial_hint):
        statement += f"，空间提示={_text(fact.spatial_hint)}"
    scope_names = [
        _text(scope.normalized_name or scope.name)
        for scope in fact.scopes
        if _text(scope.normalized_name or scope.name)
    ]
    related_mentions = _refs([*fact.related_mentions, *scope_names])
    if related_mentions:
        statement += f"，关联={'、'.join(related_mentions[:6])}"
    refs = [
        _text(fact.source_report_ref),
        f"l1:snapshot:{_text(snapshot_ref)}" if _text(snapshot_ref) else "",
    ]
    return make_l1_fact(
        statement=statement,
        fact_kind="spatial_observation",
        confidence=getattr(fact, "confidence", 0.0),
        dimension_key=fact.dimension_key,
        subject_scope=_text(fact.normalized_name),
        semantic_type=role,
        attributes={
            "mention": mention,
            "normalized_name": _text(fact.normalized_name),
            "role": role,
            "spatial_hint": _text(fact.spatial_hint),
            "scopes": json.dumps(
                [
                    {
                        "name": scope.name,
                        "normalized_name": scope.normalized_name,
                        "role": scope.role,
                        "relation_to_target": scope.relation_to_target,
                    }
                    for scope in fact.scopes
                ],
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
        source_refs=refs,
        evidence_refs=fact.evidence_refs,
        source_span=fact.source_span,
        source_snapshot_ref=snapshot_ref,
    )


def location_fact_to_l1_fact(
    fact: LocationMention,
    *,
    snapshot_ref: str = "",
) -> L1Fact | None:
    """Compatibility wrapper for the retired function name."""

    return location_mention_to_l1_fact(fact, snapshot_ref=snapshot_ref)


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
        "gis", "bundle", "bundle_geometry", "gis_layer", "data_resource_catalog",
    }:
        fact_kind = "gis_observation"
    else:
        fact_kind = "document_observation"
    if spatial_only and source_kind not in {
        "kg", "kg_canonical", "canonical_kg",
        "gis", "bundle", "bundle_geometry", "gis_layer",
        "data_resource_catalog",
    }:
        return None
    refs = [
        *_refs(getattr(fact, "source_refs", None) or []),
        _text(getattr(fact, "source_locator", "")),
    ]
    feature_ids = [
        _text(getattr(fact, "feature_bsm", "")),
        *_refs(getattr(fact, "related_parcel_bsms", None) or []),
    ]
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
        fields.get("bundle_snapshot_digest")
        or fields.get("source_snapshot_ref")
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
                "bundle", "bundle_geometry",
            }
            else "observed"
        ),
    )


__all__ = [
    "evidence_fact_to_l1_fact",
    "location_fact_to_l1_fact",
    "make_l1_fact",
    "stable_l1_fact_id",
]
