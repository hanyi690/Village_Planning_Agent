"""Deterministic construction of semantic scopes from typed L1 facts.

This module intentionally stops before KG, bundle, and geometry resolution.
It preserves the report context that is otherwise lost when a facility or road
fact is reduced to a global name lookup.  The planning context has one
administrative village scope; report-named natural villages and settlements
are semantic anchors within that scope, not nested administrative levels.
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


_NORMALIZE_SEPARATORS = frozenset(
    " ,，、;；:：|/\\()（）[]【】<>《》。.!！？?\t\n\r"
)
_VILLAGE_ROLES = {"village", "natural_village", "行政村", "自然村"}


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


def _is_village(fact: Any, normalized_name: str) -> bool:
    role = _normalize(getattr(fact, "role", ""))
    if role in {_normalize(item) for item in _VILLAGE_ROLES}:
        return True
    return normalized_name.endswith("村") or normalized_name.endswith("自然村")


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
            _text(item)
            for item in _items(_fact_value(fact, "related_mentions"))
        ),
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
            ]
        )
    )


def _matches_village(
    object_context: L1MentionContext,
    village_context: L1MentionContext,
) -> bool:
    blob = _context_blob(object_context)
    if not blob:
        return False
    village_tokens = sorted(_mention_tokens(village_context), key=len, reverse=True)
    return any(len(token) >= 2 and token in blob for token in village_tokens)


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
    village_mentions = _unique(item.normalized_name for item in villages)
    village_refs = _unique(item.mention_ref for item in villages)
    object_refs = _unique(item.mention_ref for item in objects)
    evidence_refs = _unique(
        [
            *[ref for item in villages for ref in item.evidence_refs],
            *[ref for item in objects for ref in item.evidence_refs],
        ]
    )
    relation_hints = [
        {
            "subject": item.normalized_name,
            "predicate": "located_in",
            "object": village.normalized_name,
            "source_fact_ref": item.mention_ref,
        }
        for village in villages[:1]
        for item in objects
    ]
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
            "village_count": len(villages),
            "object_count": len(objects),
            "village_mentions": village_mentions,
        }
    ]
    return L1SemanticScope(
        scope_id=_scope_id(session_id, village_refs, object_refs),
        village_mentions=village_mentions,
        village_fact_refs=village_refs,
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
    """Build deterministic village/object scopes from typed L1 facts.

    A non-village fact is attached only when its spatial hint, source span, or
    related mentions explicitly contain a village fact's name/alias.  Missing
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
        if _is_village(fact, _normalize(context.normalized_name))
    ]
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
            obj for obj in objects if _matches_village(obj, village)
        ]
        scope = _build_scope(
            session_id=session_id,
            villages=[village],
            objects=matched,
        )
        if sum(1 for obj in objects if _matches_village(obj, village)) > 0:
            matching_villages = [
                candidate
                for candidate in villages
                if any(_matches_village(obj, candidate) for obj in matched)
            ]
            if len(matching_villages) > 1:
                scope.unresolved_reasons.append("multiple_village_context")
        if l1_snapshot_ref:
            scope.query_trace.append({"step": "l1_snapshot", "ref": l1_snapshot_ref})
        scopes.append(scope)

    return scopes


__all__ = ["build_l1_semantic_scopes"]
