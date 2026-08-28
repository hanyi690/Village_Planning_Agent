"""Deterministic construction of semantic scopes from typed L1 facts.

This module intentionally stops before KG, bundle, and geometry resolution.
It preserves the report context that is otherwise lost when a facility or road
fact is reduced to a global name lookup.  Scope names are extracted from the
current L1 snapshot; they are semantic anchors, not a static place registry or
an implicit geometry boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any, Iterable

from app.contracts.evidence.l1_scope_contracts import (
    L1MentionContext,
    L1SemanticScope,
)
from app.contracts.l1.l1_contracts import LocationScopeMention


_NORMALIZE_SEPARATORS = frozenset(
    " ,，、;；:：|/\\()（）[]【】<>《》。.!！？?\t\n\r"
)
_SCOPE_ROLES = {
    "scope",
    "village",
    "natural_village",
    "administrative_village",
    "settlement",
    "place",
    "area",
    "行政村",
    "自然村",
    "村庄",
    "聚落",
    "地点",
    "区域",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fact_value(fact: Any, *keys: str) -> Any:
    attributes = getattr(fact, "attributes", None)
    attributes = attributes if isinstance(attributes, dict) else {}
    for key in keys:
        value = getattr(fact, key, None)
        if value not in (None, "", []):
            return value
        value = attributes.get(key)
        if value not in (None, "", []):
            return value
    return ""


def _items(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _normalize(value: Any) -> str:
    text = _text(value).lower()
    return "".join(char for char in text if char not in _NORMALIZE_SEPARATORS)


def _unique(values: Iterable[str]) -> list[str]:
    return list(OrderedDict.fromkeys(value for value in values if value))


def _is_scope(fact: Any, normalized_name: str) -> bool:
    role = _normalize(_fact_value(fact, "role", "semantic_type"))
    return role in {_normalize(item) for item in _SCOPE_ROLES}


def _scope_mentions(fact: Any) -> list[LocationScopeMention]:
    raw = _fact_value(fact, "scopes", "scope_mentions")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    if not raw:
        raw = [
            {"name": value, "role": "natural_village"}
            for value in _items(_fact_value(fact, "village_scopes"))
        ]
        raw.extend(
            {"name": value, "role": "place"}
            for value in _items(_fact_value(fact, "place_scopes"))
        )
    result: list[LocationScopeMention] = []
    for item in _items(raw):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name") or item.get("normalized_name"))
        if not name:
            continue
        result.append(LocationScopeMention(
            name=name,
            normalized_name=_text(item.get("normalized_name")) or name,
            role=_text(item.get("role")) or "unknown",
            relation_to_target=(
                _text(item.get("relation_to_target"))
                or _text(item.get("relation"))
                or "located_in"
            ),
            aliases=_unique(_text(value) for value in _items(item.get("aliases"))),
            source_quote=_text(item.get("source_quote")),
            source_refs=_unique(_text(value) for value in _items(item.get("source_refs"))),
            source_segment_ids=_unique(
                _text(value) for value in _items(item.get("source_segment_ids"))
            ),
            confidence=float(item.get("confidence") or 0.0),
        ))
    return result


def _fact_ref(fact: Any) -> str:
    fact_id = _text(_fact_value(fact, "fact_id"))
    if fact_id:
        return f"l1-fact:{fact_id}"
    payload = {
        "mention": _text(_fact_value(fact, "mention")),
        "normalized_name": _text(_fact_value(fact, "normalized_name")),
        "role": _text(_fact_value(fact, "role", "semantic_type")),
        "aliases": [_text(item) for item in _items(_fact_value(fact, "aliases"))],
        "spatial_hint": _text(_fact_value(fact, "spatial_hint", "location", "village")),
        "related_mentions": [
            _text(item) for item in _items(_fact_value(fact, "related_mentions"))
        ],
        "scope_mentions": [
            scope.model_dump(mode="json") for scope in _scope_mentions(fact)
        ],
        "source_report_ref": _text(_fact_value(fact, "source_report_ref")),
        "source_refs": [_text(item) for item in _items(_fact_value(fact, "source_refs"))],
        "source_span": _text(_fact_value(fact, "source_span", "statement")),
        "dimension_key": _text(_fact_value(fact, "dimension_key")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"l1-fact:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _to_context(fact: Any) -> L1MentionContext:
    normalized_name = _text(
        _fact_value(fact, "normalized_name", "name", "display_name")
    ) or _text(_fact_value(fact, "mention", "subject_scope"))
    raw_aliases = _items(_fact_value(fact, "aliases"))
    aliases = _unique(
        [
            _text(item)
            for item in raw_aliases
            if _text(item)
        ]
    )
    mention = _text(_fact_value(fact, "mention", "subject_scope")) or normalized_name
    scope_mentions = _scope_mentions(fact)
    source_refs = [
        _text(item) for item in (_fact_value(fact, "source_refs") or []) if _text(item)
    ]
    return L1MentionContext(
        mention_ref=_fact_ref(fact),
        mention=mention,
        normalized_name=normalized_name,
        role=_text(_fact_value(fact, "role", "semantic_type")) or "unknown",
        aliases=aliases,
        spatial_hint=_text(
            _fact_value(fact, "spatial_hint", "location", "village", "settlement")
        ),
        related_mentions=_unique(
            [
                *[
                    _text(item)
                    for item in _items(_fact_value(fact, "related_mentions"))
                ],
                *[scope.name for scope in scope_mentions],
            ]
        ),
        scope_mentions=scope_mentions,
        source_report_ref=_text(_fact_value(fact, "source_report_ref")) or (
            source_refs[0] if source_refs else ""
        ),
        source_span=_text(_fact_value(fact, "source_span", "statement")),
        dimension_key=_text(_fact_value(fact, "dimension_key")),
        evidence_refs=_unique(
            [
                *[_text(item) for item in (_fact_value(fact, "evidence_refs") or [])],
                *source_refs,
            ]
        ),
        confidence=float(_fact_value(fact, "confidence") or 0.0),
    )


def _mention_tokens(context: L1MentionContext) -> list[str]:
    return _unique(
        _normalize(value)
        for value in [
            context.normalized_name,
            context.mention,
            *context.aliases,
        ]
        if _normalize(value)
    )


def _context_blob(context: L1MentionContext) -> str:
    return _normalize(
        " ".join(
            [
                context.spatial_hint,
                context.source_span,
                *context.related_mentions,
                *[
                    scope.name
                    for scope in context.scope_mentions
                ],
            ]
        )
    )


def _matches_scope(
    object_context: L1MentionContext,
    scope_context: L1MentionContext,
) -> bool:
    blob = _context_blob(object_context)
    if not blob:
        return False
    scope_tokens = sorted(_mention_tokens(scope_context), key=len, reverse=True)
    return any(len(token) >= 2 and token in blob for token in scope_tokens)


def _scope_id(session_id: str, village_refs: list[str], object_refs: list[str]) -> str:
    payload = {
        "session_id": _text(session_id),
        "village_refs": sorted(village_refs),
        "object_refs": sorted(object_refs),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"l1-scope:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _build_scope(
    *,
    session_id: str,
    villages: list[L1MentionContext],
    objects: list[L1MentionContext],
) -> L1SemanticScope:
    declared_scopes: list[LocationScopeMention] = []
    for village in villages:
        declared_scopes.append(LocationScopeMention(
            name=village.normalized_name,
            normalized_name=village.normalized_name,
            role=village.role or "scope",
            relation_to_target="located_in",
            aliases=village.aliases,
        ))
    declared_scopes.extend(
        scope
        for item in objects
        for scope in item.scope_mentions
    )
    scope_mentions: list[LocationScopeMention] = []
    seen_scope_keys: set[tuple[str, str, str]] = set()
    for scope in declared_scopes:
        key = (
            _normalize(scope.normalized_name or scope.name),
            _normalize(scope.role),
            _normalize(scope.relation_to_target),
        )
        if not key[0] or key in seen_scope_keys:
            continue
        seen_scope_keys.add(key)
        scope_mentions.append(scope)
    village_mentions = _unique(
        scope.normalized_name or scope.name
        for scope in scope_mentions
    )
    village_refs = _unique(item.mention_ref for item in villages)
    object_refs = _unique(item.mention_ref for item in objects)
    evidence_refs = _unique(
        [
            *[ref for item in villages for ref in item.evidence_refs],
            *[ref for item in objects for ref in item.evidence_refs],
        ]
    )
    relation_hints = []
    for item in objects:
        for scope in item.scope_mentions:
            relation_hints.append({
                "subject": item.normalized_name,
                "predicate": scope.relation_to_target or "located_in",
                "object": scope.normalized_name or scope.name,
                "source_fact_ref": item.mention_ref,
            })
        if not item.scope_mentions:
            relation_hints.extend({
                "subject": item.normalized_name,
                "predicate": "located_in",
                "object": village.normalized_name,
                "source_fact_ref": item.mention_ref,
            } for village in villages[:1])
    confidence_values = [item.confidence for item in [*villages, *objects] if item.confidence]
    confidence = min(confidence_values) if confidence_values else 0.0
    reasons: list[str] = []
    if not villages:
        reasons.append("missing_village_context")
    elif len(villages) > 1:
        reasons.append("multiple_village_context")
    trace = [
        {
            "step": "l1_scope",
            "scope_count": len(villages),
            "village_count": len(villages),
            "scope_mentions": village_mentions,
            "object_count": len(objects),
            "village_mentions": village_mentions,
        }
    ]
    return L1SemanticScope(
        scope_id=_scope_id(session_id, village_refs, object_refs),
        village_mentions=village_mentions,
        village_fact_refs=village_refs,
        scope_mentions=scope_mentions,
        object_mentions=objects,
        relation_hints=relation_hints,
        source_observation_refs=_unique([*village_refs, *object_refs]),
        evidence_refs=evidence_refs,
        confidence=confidence,
        unresolved_reasons=reasons,
        query_trace=trace,
    )


def build_l1_semantic_scopes(
    facts: Iterable[Any],
    *,
    session_id: str = "",
    l1_snapshot_ref: str = "",
) -> list[L1SemanticScope]:
    """Build deterministic named-scope/object relations from typed L1 facts.

    A non-scope fact is attached only when its spatial hint, source span, or
    related mentions explicitly contain a report-derived scope name.  Missing
    context remains unresolved; this function never invents a geometry or
    chooses a bundle feature.
    """

    raw_facts = list(facts)
    fact_contexts = [
        (fact, _to_context(fact))
        for fact in raw_facts
    ]
    fact_contexts = [
        (fact, context)
        for fact, context in fact_contexts
        if context.normalized_name
    ]
    villages = [
        context
        for fact, context in fact_contexts
        if _is_scope(fact, _normalize(context.normalized_name))
    ]
    virtual_villages: dict[str, L1MentionContext] = {}
    for _fact, context in fact_contexts:
        for scope in context.scope_mentions:
            if _normalize(scope.role) not in {
                _normalize(item) for item in _SCOPE_ROLES
            }:
                continue
            key = _normalize(scope.normalized_name or scope.name)
            if not key or key in virtual_villages:
                continue
            virtual_villages[key] = L1MentionContext(
                mention_ref=f"l1-scope-mention:{key}",
                mention=scope.name,
                normalized_name=scope.normalized_name or scope.name,
                role=scope.role,
                aliases=scope.aliases,
                source_report_ref=(scope.source_refs or [""])[0],
                evidence_refs=scope.source_refs + scope.source_segment_ids,
                scope_mentions=[scope],
                confidence=scope.confidence,
            )
    direct_village_keys = {
        _normalize(item.normalized_name) for item in villages
    }
    villages.extend(
        context
        for key, context in virtual_villages.items()
        if key not in direct_village_keys
    )
    village_refs = {context.mention_ref for context in villages}
    objects = [
        context
        for _fact, context in fact_contexts
        if context.mention_ref not in village_refs
    ]

    if not villages:
        scope = _build_scope(session_id=session_id, villages=[], objects=objects)
        if l1_snapshot_ref:
            scope.query_trace.append({"step": "l1_snapshot", "ref": l1_snapshot_ref})
        return [scope]

    scopes: list[L1SemanticScope] = []
    for village in villages:
        matched = [
            obj for obj in objects if _matches_scope(obj, village)
        ]
        scope = _build_scope(
            session_id=session_id,
            villages=[village],
            objects=matched,
        )
        if sum(1 for obj in objects if _matches_scope(obj, village)) > 0:
            matching_villages = [
                candidate
                for candidate in villages
                if any(_matches_scope(obj, candidate) for obj in matched)
            ]
            if len(matching_villages) > 1:
                scope.unresolved_reasons.append("multiple_village_context")
        if l1_snapshot_ref:
            scope.query_trace.append({"step": "l1_snapshot", "ref": l1_snapshot_ref})
        scopes.append(scope)

    return scopes


__all__ = ["build_l1_semantic_scopes"]
