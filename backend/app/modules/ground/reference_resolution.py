"""GROUND reference-resolution boundary.

This module owns both spatial entry points:

* L1 semantic ``LocationMention`` -> source-backed entity binding; and
* post-L3 ``SpatialReferenceSpec`` -> planning candidate resolution.

The first entry point is deliberately independent of TARGET_PROJECTION.  L1
mentions are already useful spatial work items before a planning intent exists.
The resolver may use an LLM only as a closed-set selector; all identities,
feature references and geometry references still come from the current source
context and are validated by the spatial runtime.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.contracts.evidence.identity_contracts import (
    GroundedEntityBinding,
)
from app.contracts.ground.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
    normalize_spatial_role,
)
from app.spatial.grounding.resolver import SpatialResolver


_ROLE_SCOPES = {
    "facility": ("facilities", "parcels"),
    "landmark": ("facilities", "parcels"),
    "road": ("roads", "parcels"),
    "water": ("waters", "parcels"),
    "hazard": ("hazards", "facilities"),
    "project": ("facilities", "parcels"),
    "area": ("zones", "parcels"),
    "natural_village": ("parcels", "facilities"),
    "administrative_village": ("parcels", "facilities"),
    "settlement": ("parcels", "facilities"),
}


def _value(item: Any, field: str, default: str = "") -> str:
    if isinstance(item, dict):
        return str(item.get(field, default) or "").strip()
    return str(getattr(item, field, default) or "").strip()


def _scope_values(mention: Any) -> list[str]:
    values: list[str] = []
    for scope in list(getattr(mention, "scopes", None) or []):
        value = _value(scope, "normalized_name") or _value(scope, "name")
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _relation_values(mention: Any) -> list[str]:
    raw = (
        mention.get("related_mentions", [])
        if isinstance(mention, dict)
        else getattr(mention, "related_mentions", None)
    ) or []
    return list(dict.fromkeys(
        str(value).strip()
        for value in raw
        if str(value).strip()
    ))


def _mention_spec(mention: Any, observation_ref: str, context: Any) -> SpatialReferenceSpec:
    """Compile one semantic mention into a runtime-owned spatial query.

    Only the query semantics are copied from L1.  Runtime identities and
    source lineage are supplied here by the current context; no provider ID,
    coordinate, BSM or geometry is accepted from the mention.
    """

    name = _value(mention, "normalized_name") or _value(mention, "mention")
    role = normalize_spatial_role(_value(mention, "role", "unknown"))
    scopes = _scope_values(mention)
    relations = _relation_values(mention)
    semantic_terms = list(dict.fromkeys([
        name,
        *scopes,
        _value(mention, "spatial_hint"),
        *relations,
    ]))
    semantic_terms = [value for value in semantic_terms if value][:8]
    snapshot = str(getattr(context, "l1_snapshot_ref", "") or "").strip()
    bundle_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    ).strip()
    return SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": name}),
        semantic_terms=semantic_terms,
        retrieval_scopes=list(_ROLE_SCOPES.get(role, ("facilities", "roads", "waters", "parcels"))),
        target_id=observation_ref,
        spec_id=f"l1-ground:{observation_ref}",
        source_snapshot_ref=snapshot,
        source_snapshot_digest=bundle_digest,
        l1_fact_refs=[
            value
            for value in (
                _value(mention, "fact_id"),
                *list(getattr(mention, "evidence_refs", None) or []),
            )
            if value
        ],
        unresolved_reason="l1_location_mention",
    )


_NON_SPATIAL_NAME_SUFFIXES = (
    "发展",
    "现状评估",
    "评估",
    "规范缺失",
    "维护缺失",
    "缺失",
    "场地不足",
    "不足",
    "分布零散",
    "设施完善",
    "交通条件",
)
_ENTITY_ALIAS_SUFFIXES = (
    "村民委员会",
    "居民委员会",
    "村委会",
    "委员会",
)
_SYSTEM_ATTRIBUTE_FIELDS = {
    "admission_reason",
    "admission_signals",
    "admission_status",
    "content_digest",
    "document_name",
    "input_role",
    "layer_ref",
    "resource_kind",
    "source_crs",
    "source_digest",
    "source_feature_ref",
    "source_record_id",
    "source_uri",
    "upload_filename",
}

_RELATION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("west_of", ("west_of", "west of", "西侧", "西面", "西边", "以西")),
    ("east_of", ("east_of", "east of", "东侧", "东面", "东边", "以东")),
    ("north_of", ("north_of", "north of", "北侧", "北面", "北边", "以北")),
    ("south_of", ("south_of", "south of", "南侧", "南面", "南边", "以南")),
    ("adjacent_to", ("adjacent_to", "adjacent to", "相邻", "毗邻")),
    ("between", ("between", "之间")),
    ("along", ("along", "沿着", "沿线", "沿")),
    ("near", ("nearby", "near", "vicinity", "附近", "周边", "邻近", "靠近")),
    ("within", ("located_in", "located in", "within", "位于", "内部", "范围内")),
)


def _normalized_relation(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    compact = re.sub(r"[\s\-]+", "_", text)
    for relation, markers in _RELATION_MARKERS:
        if compact == relation:
            return relation
        if any(marker.casefold() in text for marker in markers):
            return relation
    return ""


def _scope_signature(mention: Any) -> tuple[str, ...]:
    return tuple(sorted({
        key
        for key in (_name_key(value) for value in _scope_values(mention))
        if key
    }))


def _phrase_anchor_labels(value: Any, relation: str) -> list[str]:
    text = str(value or "").strip()
    if not text or not relation:
        return []
    labels: list[str] = []
    markers = next((items for key, items in _RELATION_MARKERS if key == relation), ())
    lowered = text.casefold()
    for marker in markers:
        marker_text = marker.casefold()
        position = lowered.find(marker_text)
        if position < 0:
            continue
        before = text[:position].strip(" ,，。;；:：_-—–在于")
        after = text[position + len(marker):].strip(" ,，。;；:：_-—–在于")
        if relation == "between":
            combined = before or after
            labels.extend(
                part.strip()
                for part in re.split(r"(?:与|和|及|、|,|，|and)", combined)
                if part.strip()
            )
        elif relation == "along":
            label = after or before
            if label:
                labels.append(label)
        else:
            label = before or after
            if label:
                labels.append(label)
        break
    return list(dict.fromkeys(labels))


def _relative_location_inputs(mention: Any) -> tuple[str, list[str], str]:
    names = list(dict.fromkeys(
        value
        for value in (
            _value(mention, "normalized_name"),
            _value(mention, "mention"),
        )
        if value
    ))
    name_relations = [
        relation for name in names if (relation := _normalized_relation(name))
    ]
    explicit_relation = _normalized_relation(_value(mention, "relation"))
    hint = _value(mention, "spatial_hint")
    hint_relation = _normalized_relation(hint)
    relation_sources = [
        value
        for value in (
            explicit_relation,
            *name_relations,
            hint_relation,
        )
        if value
    ]
    relations = list(dict.fromkeys(relation_sources))
    if not relations:
        return "", [], ""
    relation = relations[0]
    phrase_labels = [
        label
        for name in (*names, hint)
        for label in _phrase_anchor_labels(name, relation)
    ]
    scope_labels = _scope_values(mention)
    scope_keys = {_name_key(value) for value in scope_labels}
    raw_related = _relation_values(mention)
    non_scope_related = [
        value for value in raw_related if _name_key(value) not in scope_keys
    ]
    related_labels = non_scope_related or scope_labels or raw_related
    own_keys = {
        _name_key(value)
        for value in names
        if _name_key(value)
    }
    labels = list(dict.fromkeys(
        value
        for value in (*phrase_labels, *related_labels)
        if value and _name_key(value) not in own_keys
    ))
    conflict = ",".join(relations[1:])
    return relation, labels, conflict


def _distance_hint(mention: Any) -> str:
    text = " ".join(filter(None, (
        _value(mention, "mention"),
        _value(mention, "spatial_hint"),
        _value(mention, "source_span"),
    )))
    match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*(公里|千米|km|米|m)(?![a-z])",
        text,
        flags=re.IGNORECASE,
    )
    return "" if match is None else f"{match.group(1)}{match.group(2).lower()}"


def _expression_ref(
    mention_ref: str,
    relation: str,
    labels: list[str],
) -> str:
    payload = "|".join((
        mention_ref,
        relation,
        *sorted({_name_key(value) for value in labels if _name_key(value)}),
    ))
    return f"location-expression:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _list_values(item: Any, field: str) -> list[str]:
    raw = item.get(field, []) if isinstance(item, dict) else getattr(item, field, [])
    if isinstance(raw, str):
        raw = [raw]
    return list(dict.fromkeys(
        str(value).strip()
        for value in (raw or [])
        if str(value).strip()
    ))


def _name_key(value: Any) -> str:
    return re.sub(r"[\s·•_\-—–,，。;；:：/\\]+", "", str(value or "")).casefold()


def _location_alias_keys(value: Any) -> set[str]:
    key = _name_key(value)
    result = {key} if key else set()
    for suffix in _ENTITY_ALIAS_SUFFIXES:
        suffix_key = _name_key(suffix)
        if key.endswith(suffix_key) and len(key) > len(suffix_key) + 1:
            result.add(key[:-len(suffix_key)])
    return result


def _is_location_work_item(mention: Any) -> bool:
    if _list_values(mention, "source_feature_ids"):
        return True
    mention_kind = _value(mention, "mention_kind", "target")
    if mention_kind in {"place", "anchor_request"}:
        return True
    name = _value(mention, "normalized_name") or _value(mention, "mention")
    if not name:
        return False
    return not any(name.endswith(suffix) for suffix in _NON_SPATIAL_NAME_SUFFIXES)


def _current_world_port(context: Any) -> Any:
    """Return the only world-model capability allowed to Ground reads."""
    current_port = getattr(getattr(context, "ports", None), "current_world", None)
    return current_port


def _catalog_location_index(
    context: Any,
    catalog: Any,
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[tuple[str, str]]]]:
    snapshot = getattr(catalog, "snapshot", None)
    token = str(getattr(snapshot, "digest", "") or id(snapshot))
    cached = getattr(context, "_l1_catalog_location_index", None)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == token:
        return cached[1], cached[2]
    exact: dict[str, dict[tuple[str, str], None]] = {}
    aliases: dict[str, dict[tuple[str, str], None]] = {}
    for feature in getattr(snapshot, "features", ()) or ():
        if str(getattr(feature, "geometry_kind", "unknown") or "unknown") not in {
            "point", "line", "polygon", "multipatch",
        }:
            continue
        feature_key = (
            str(getattr(feature, "dataset_ref", "") or ""),
            str(getattr(feature, "source_feature_ref", "") or ""),
        )
        fields = {
            **dict(getattr(feature, "raw_attributes", {}) or {}),
            **dict(getattr(feature, "normalized_claims", {}) or {}),
        }
        for field_name, raw_value in fields.items():
            field_key = str(field_name or "").strip().casefold()
            if (
                not field_key
                or field_key in _SYSTEM_ATTRIBUTE_FIELDS
                or field_key.startswith("source_")
                or field_key.startswith("admission_")
            ):
                continue
            if not isinstance(raw_value, str):
                continue
            text = raw_value.strip()
            if not 1 < len(text) <= 96 or "://" in text or text.startswith("sha256:"):
                continue
            keys = _location_alias_keys(text)
            if not keys:
                continue
            primary = _name_key(text)
            exact.setdefault(primary, {})[feature_key] = None
            for alias in keys - {primary}:
                aliases.setdefault(alias, {})[feature_key] = None
    exact_result = {key: list(values) for key, values in exact.items()}
    alias_result = {key: list(values) for key, values in aliases.items()}
    setattr(context, "_l1_catalog_location_index", (token, exact_result, alias_result))
    return exact_result, alias_result


def _entity_rows_for_sources(
    port: Any,
    source_keys: list[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not callable(getattr(port, "find_entities", None)):
        return result
    for _dataset_ref, source_ref in source_keys:
        for entity in port.find_entities(
            source_feature_ref=source_ref,
            limit=16,
        ) or []:
            entity_ref = str(entity.get("entity_ref") or "")
            if entity_ref:
                result.setdefault(entity_ref, entity)
    return result


def _binding_from_entity_rows(
    context: Any,
    mention: Any,
    mention_ref: str,
    entity_rows: dict[str, dict[str, Any]],
    *,
    match_mode: str,
    evidence_refs: list[str] | None = None,
) -> GroundedEntityBinding:
    port = _current_world_port(context)
    world_model = port
    world_model_snapshot_ref = str(
        getattr(world_model, "snapshot_ref", "") or ""
    )
    world_model_snapshot_digest = str(
        getattr(world_model, "snapshot_digest", "") or ""
    )
    if callable(getattr(port, "find_entities", None)):
        expanded_rows: dict[str, dict[str, Any]] = {}
        for entity_ref, row in entity_rows.items():
            full_rows = port.find_entities(
                entity_ref=entity_ref,
                limit=1,
            ) or []
            expanded_rows[entity_ref] = full_rows[0] if full_rows else row
        entity_rows = expanded_rows
    entity_refs = sorted(entity_rows)
    mention_evidence = list(dict.fromkeys([
        *_list_values(mention, "evidence_refs"),
        *(evidence_refs or []),
    ]))
    source_feature_ids = sorted({
        str(part.get("source_feature_ref") or "")
        for entity in entity_rows.values()
        for part in (entity.get("parts", ()) or ())
        if str(part.get("source_feature_ref") or "")
    })
    if len(entity_refs) != 1:
        status = "ambiguous" if entity_refs else "unresolved"
        return GroundedEntityBinding(
            binding_id=f"ground:v2:{mention_ref}",
            mention_ref=mention_ref,
            observation_refs=[mention_ref],
            status=status,
            source_feature_ids=source_feature_ids,
            candidate_refs=entity_refs,
            candidate_entity_refs=entity_refs,
            evidence_refs=mention_evidence,
            confidence=0.5 if entity_refs else 0.0,
            uncertainty_reason=(
                f"{match_mode}_multiple_entities"
                if entity_refs
                else f"{match_mode}_no_entity"
            ),
            query_trace=[{
                "step": "v2_indexed_location_match",
                "match_mode": match_mode,
                "mention_ref": mention_ref,
                "entity_candidate_count": len(entity_refs),
                "source_feature_count": len(source_feature_ids),
            }],
            world_model_snapshot_ref=world_model_snapshot_ref,
            world_model_snapshot_digest=world_model_snapshot_digest,
        )
    entity_ref = entity_refs[0]
    representations = (
        port.representations_for(entity_ref, limit=256)
        if callable(getattr(port, "representations_for", None))
        else []
    )
    representation_refs = sorted({
        str(item.get("representation_ref") or "")
        for item in representations
        if str(item.get("representation_ref") or "")
    })
    geometry_refs = sorted({
        str(item.get("geometry_ref") or "")
        for item in representations
        if str(item.get("geometry_ref") or "")
    })
    resource_refs = sorted({
        str(item.get("resource_ref") or "")
        for item in representations
        if str(item.get("resource_ref") or "")
    })
    entity_part_refs = sorted({
        str(item.get("entity_part_ref") or "")
        for item in representations
        if str(item.get("entity_part_ref") or "")
    })
    has_geometry = bool(geometry_refs and representation_refs and resource_refs)
    is_feature_set = (
        len(source_feature_ids) > 1
        or len(geometry_refs) > 1
        or len(representation_refs) > 1
    )
    status = (
        "feature_set"
        if has_geometry and is_feature_set
        else "exact_feature"
        if has_geometry
        else "name_only"
    )
    return GroundedEntityBinding(
        binding_id=f"ground:v2:{mention_ref}",
        mention_ref=mention_ref,
        canonical_entity_ref=entity_ref,
        observation_refs=[mention_ref],
        status=status,
        geometry_granularity=(
            "feature_set"
            if status == "feature_set"
            else "exact_feature"
            if status == "exact_feature"
            else "none"
        ),
        geometry_ref=geometry_refs[0] if len(geometry_refs) == 1 else None,
        geometry_refs=geometry_refs,
        representation_refs=representation_refs,
        resource_refs=resource_refs,
        entity_part_refs=entity_part_refs,
        source_feature_ids=source_feature_ids,
        candidate_refs=[entity_ref],
        candidate_entity_refs=[entity_ref],
        evidence_refs=mention_evidence,
        confidence=1.0 if has_geometry else 0.8,
        uncertainty_reason=(
            f"{match_mode}_entity_with_representations"
            if has_geometry
            else f"{match_mode}_entity_without_executable_representation"
        ),
        query_trace=[{
            "step": "v2_indexed_location_match",
            "match_mode": match_mode,
            "mention_ref": mention_ref,
            "entity_candidate_count": 1,
            "source_feature_count": len(source_feature_ids),
            "representation_count": len(representation_refs),
            "geometry_count": len(geometry_refs),
            "resource_count": len(resource_refs),
        }],
        world_model_snapshot_ref=world_model_snapshot_ref,
        world_model_snapshot_digest=world_model_snapshot_digest,
    )


def _scope_compatible(
    expression_scope: tuple[str, ...],
    anchor_scope: tuple[str, ...],
    anchor_label_key: str,
) -> bool:
    if not expression_scope:
        return True
    if expression_scope == anchor_scope:
        return True
    return not anchor_scope and anchor_label_key in expression_scope


def _append_uncertainty_reason(current: str, reason: str) -> str:
    values = [
        value
        for value in str(current or "").split(";")
        if value
    ]
    if reason and reason not in values:
        values.append(reason)
    return ";".join(values)


def _bind_relative_location_expressions(
    context: Any,
    mentions: list[Any],
    bindings: list[GroundedEntityBinding],
) -> list[GroundedEntityBinding]:
    """Bind fuzzy relations to admitted WorldEntity identities only.

    This pass records a semantic expression and anchor identities.  It never
    selects a representation and never derives a buffer, centroid or other
    executable geometry.
    """

    if not bindings:
        return []
    port = _current_world_port(context)
    mention_by_ref: dict[str, Any] = {}
    for index, mention in enumerate(mentions):
        mention_ref = (
            _value(mention, "work_item_ref")
            or _value(mention, "fact_id")
            or f"l1-mention:{index}"
        )
        mention_by_ref.setdefault(mention_ref, mention)

    anchors_by_label: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
    for binding in bindings:
        entity_ref = str(binding.canonical_entity_ref or "").strip()
        mention = mention_by_ref.get(binding.mention_ref)
        if not entity_ref or mention is None:
            continue
        relation, _anchor_labels, _conflict = _relative_location_inputs(mention)
        own_labels = list(dict.fromkeys(
            value
            for value in (
                _value(mention, "normalized_name"),
                _value(mention, "mention"),
                *_list_values(mention, "aliases"),
            )
            if value
        ))
        phrase_labels = list(dict.fromkeys(
            label
            for value in own_labels
            for label in _phrase_anchor_labels(value, relation)
        )) if relation else []
        labels = list(dict.fromkeys([*own_labels, *phrase_labels]))
        scope = _scope_signature(mention)
        for label in labels:
            label_key = _name_key(label)
            if not label_key:
                continue
            entry = (entity_ref, binding.mention_ref, scope)
            bucket = anchors_by_label.setdefault(label_key, [])
            if entry not in bucket:
                bucket.append(entry)

    result: list[GroundedEntityBinding] = []
    for binding in bindings:
        mention = mention_by_ref.get(binding.mention_ref)
        if mention is None:
            result.append(binding)
            continue
        relation, anchor_labels, relation_conflict = _relative_location_inputs(
            mention
        )
        if not relation:
            result.append(binding)
            continue
        expression_scope = _scope_signature(mention)
        anchor_entries: list[tuple[str, str]] = []
        unmatched_labels: list[str] = []
        for label in anchor_labels:
            label_key = _name_key(label)
            indexed = list(anchors_by_label.get(label_key, ()))
            compatible = [
                (entity_ref, work_item_ref)
                for entity_ref, work_item_ref, anchor_scope in indexed
                if _scope_compatible(
                    expression_scope,
                    anchor_scope,
                    label_key,
                )
            ]
            direct_lookup_allowed = (
                not expression_scope or label_key in expression_scope
            )
            if (
                not compatible
                and not indexed
                and direct_lookup_allowed
                and callable(getattr(port, "find_entities", None))
            ):
                compatible = [
                    (str(row.get("entity_ref") or "").strip(), "")
                    for row in (port.find_entities(name=label, limit=64) or [])
                    if str(row.get("entity_ref") or "").strip()
                ]
            if not compatible:
                unmatched_labels.append(label)
                continue
            for entry in compatible:
                if entry not in anchor_entries:
                    anchor_entries.append(entry)
        if not anchor_labels and binding.canonical_entity_ref:
            anchor_entries.append((binding.canonical_entity_ref, binding.mention_ref))

        anchor_entity_refs = sorted({
            entity_ref for entity_ref, _work_item_ref in anchor_entries if entity_ref
        })
        anchor_work_item_refs = sorted({
            work_item_ref
            for _entity_ref, work_item_ref in anchor_entries
            if work_item_ref
        })
        if relation_conflict:
            expression_status = "ambiguous"
            gap_reason = "relative_location_relation_ambiguous"
        elif unmatched_labels:
            expression_status = "unresolved"
            gap_reason = "relative_location_anchor_unresolved"
        elif relation == "between":
            expression_status = "bound" if len(anchor_entity_refs) >= 2 else "unresolved"
            gap_reason = (
                "relative_location_expression_bound"
                if expression_status == "bound"
                else "relative_location_between_requires_two_anchors"
            )
        elif len(anchor_entity_refs) == 1:
            expression_status = "bound"
            gap_reason = "relative_location_expression_bound"
        elif len(anchor_entity_refs) > 1:
            expression_status = "ambiguous"
            gap_reason = "relative_location_anchor_ambiguous"
        else:
            expression_status = "unresolved"
            gap_reason = "relative_location_anchor_unresolved"

        expression_ref = _expression_ref(
            binding.mention_ref,
            relation,
            anchor_labels,
        )
        phrase_anchor_labels = list(dict.fromkeys(
            label
            for value in (
                _value(mention, "normalized_name"),
                _value(mention, "mention"),
            )
            for label in _phrase_anchor_labels(value, relation)
        ))
        expression_only = bool(
            phrase_anchor_labels
            and not binding.canonical_entity_ref
            and not binding.candidate_entity_refs
        )
        relation_evidence_refs = list(dict.fromkeys([
            *list(binding.relation_evidence_refs or []),
            *_list_values(mention, "evidence_refs"),
            *_list_values(
                getattr(mention, "provenance", None) or {},
                "source_refs",
            ),
        ]))
        trace = [
            *list(binding.query_trace or []),
            {
                "step": "ground_l1_relative_location_binding",
                "mention_ref": binding.mention_ref,
                "relation": relation,
                "expression_status": expression_status,
                "anchor_labels": anchor_labels[:8],
                "anchor_entity_count": len(anchor_entity_refs),
                "unmatched_anchor_labels": unmatched_labels[:8],
                "scope_keys": list(expression_scope)[:8],
                "relation_conflict": relation_conflict,
                "geometry_operation": "none",
            },
        ]
        update = {
            "location_expression_ref": expression_ref,
            "location_expression_status": expression_status,
            "spatial_relation": relation,
            "anchor_entity_refs": anchor_entity_refs,
            "anchor_work_item_refs": anchor_work_item_refs,
            "distance_hint": _distance_hint(mention),
            "relation_evidence_refs": relation_evidence_refs,
            "uncertainty_reason": _append_uncertainty_reason(
                binding.uncertainty_reason,
                gap_reason,
            ),
            "query_trace": trace[-32:],
        }
        if expression_only and expression_status == "bound":
            update.update({
                "status": "not_applicable",
                "identity_status": "not_applicable",
                "geometry_granularity": "none",
                "geometry_ref": None,
                "geometry_refs": [],
                "representation_refs": [],
                "resource_refs": [],
                "entity_part_refs": [],
                "source_feature_ids": [],
            })
        result.append(GroundedEntityBinding.model_validate({
            **binding.model_dump(mode="python"),
            **update,
        }))
    return result


def _selected_packet_ref(
    packet: Any,
    mention_ref: str,
    decisions: dict[str, Any],
) -> Any:
    refs = list(getattr(packet, "candidate_refs", None) or [])
    if len(refs) == 1:
        return refs[0]
    selected_id = ""
    for decision in decisions.values():
        if not isinstance(decision, dict):
            continue
        if str(decision.get("observation_id") or "") != mention_ref:
            continue
        if str(decision.get("status") or "") == "selected":
            selected_id = str(decision.get("selected_candidate_id") or "")
        break
    if not selected_id:
        return None
    from app.contracts.ground.spatial_reference_contracts import (
        spatial_candidate_descriptor,
    )

    for candidate in refs:
        descriptor = spatial_candidate_descriptor(
            candidate,
            kind="spatial_candidate",
        )
        if descriptor.candidate_id == selected_id:
            return candidate
    return None


def _resolve_l1_catalog_mentions(
    context: Any,
    mentions: list[Any],
    *,
    evidence_packets: dict[str, Any] | None = None,
    candidate_selection_decisions: dict[str, Any] | None = None,
) -> list[GroundedEntityBinding]:
    """Resolve L1 places immediately through indexed DATA/KG identities."""

    catalog = getattr(context, "data_resource_catalog", None)
    port = _current_world_port(context)
    exact_index, alias_index = _catalog_location_index(
        context, catalog
    )
    bindings: list[GroundedEntityBinding] = []
    packets = evidence_packets or {}
    decisions = candidate_selection_decisions or {}
    for index, mention in enumerate(mentions):
        mention_ref = (
            _value(mention, "work_item_ref")
            or _value(mention, "fact_id")
            or f"l1-mention:{index}"
        )
        if not _is_location_work_item(mention):
            bindings.append(GroundedEntityBinding(
                binding_id=f"ground:v2:{mention_ref}",
                mention_ref=mention_ref,
                observation_refs=[mention_ref],
                status="not_applicable",
                evidence_refs=_list_values(mention, "evidence_refs"),
                uncertainty_reason="l1_fact_is_not_a_spatial_entity",
                query_trace=[{
                    "step": "l1_location_work_item_filter",
                    "mention_ref": mention_ref,
                    "decision": "not_applicable",
                }],
            ))
            continue

        names = list(dict.fromkeys(
            value
            for value in (
                _value(mention, "normalized_name"),
                _value(mention, "mention"),
                *_list_values(mention, "aliases"),
            )
            if value
        ))
        source_keys: list[tuple[str, str]] = []
        match_mode = "none"
        direct_source_ids = _list_values(mention, "source_feature_ids")
        if direct_source_ids:
            match_mode = "l1_source_feature_ref"
            for source_ref in direct_source_ids:
                feature = (
                    catalog.get_feature(source_ref)
                    if callable(getattr(catalog, "get_feature", None))
                    else None
                )
                source_keys.append((
                    str(getattr(feature, "dataset_ref", "") or ""),
                    source_ref,
                ))
        entity_rows: dict[str, dict[str, Any]] = {}
        if not source_keys and callable(getattr(port, "find_entities", None)):
            for name in names:
                for entity in port.find_entities(name=name, limit=64) or []:
                    entity_ref = str(entity.get("entity_ref") or "")
                    if entity_ref:
                        entity_rows.setdefault(entity_ref, entity)
            if entity_rows:
                match_mode = "world_model_name"
        if not source_keys and not entity_rows:
            for name in names:
                source_keys.extend(exact_index.get(_name_key(name), ()))
            source_keys = list(dict.fromkeys(source_keys))
            if source_keys:
                match_mode = "data_attribute_exact"
        if not source_keys and not entity_rows:
            for name in names:
                source_keys.extend(alias_index.get(_name_key(name), ()))
            source_keys = list(dict.fromkeys(source_keys))
            if source_keys:
                match_mode = "data_attribute_alias"
        if source_keys and not entity_rows:
            entity_rows = _entity_rows_for_sources(port, source_keys)

        base = _binding_from_entity_rows(
            context,
            mention,
            mention_ref,
            entity_rows,
            match_mode=match_mode,
        )
        packet = packets.get(mention_ref)
        if (
            packet is not None
            and base.status in {"ambiguous", "unresolved", "name_only"}
        ):
            selected = _selected_packet_ref(
                packet,
                mention_ref,
                decisions,
            )
            candidate_refs = (
                [selected]
                if selected is not None
                else list(getattr(packet, "candidate_refs", None) or [])
            )
            packet_entity_rows: dict[str, dict[str, Any]] = {}
            packet_evidence_refs: list[str] = []
            for candidate in candidate_refs:
                identity = getattr(candidate, "identity", None)
                source_ref = str(
                    getattr(identity, "source_feature_id", "") or ""
                )
                entity_refs = [
                    str(value)
                    for value in (
                        getattr(candidate, "entity_refs", None) or []
                    )
                    if str(value).strip()
                ]
                for entity_ref in entity_refs:
                    rows = port.find_entities(
                        entity_ref=entity_ref,
                        limit=1,
                    ) if callable(getattr(port, "find_entities", None)) else []
                    if rows:
                        packet_entity_rows.setdefault(entity_ref, rows[0])
                if not entity_refs and source_ref:
                    packet_entity_rows.update(
                        _entity_rows_for_sources(port, [("", source_ref)])
                    )
                packet_evidence_refs.extend(
                    str(value)
                    for value in (
                        getattr(candidate, "provenance_refs", None) or []
                    )
                    if str(value).strip()
                )
            if packet_entity_rows:
                base = _binding_from_entity_rows(
                    context,
                    mention,
                    mention_ref,
                    packet_entity_rows,
                    match_mode=(
                        "evidence_closed_set_selected"
                        if selected is not None
                        else "evidence_candidate_set"
                    ),
                    evidence_refs=packet_evidence_refs,
                )
        bindings.append(base)
    return _bind_relative_location_expressions(context, mentions, bindings)


def resolve_l1_location_mentions(
    context: Any,
    *,
    ground_llm_budget: dict[str, Any] | None = None,
    evidence_packets: dict[str, Any] | None = None,
    candidate_selection_decisions: dict[str, Any] | None = None,
    max_rounds: int = 2,
) -> list[GroundedEntityBinding]:
    """Resolve every L1 location work item against current source evidence.

    The loop is deliberately bounded and resumable.  A resolved mention is
    placed on ``context.grounded_bindings`` so later mention queries may use it
    as a scope/anchor; unresolved and ambiguous items remain explicit and are
    never converted into executable candidates.
    """

    mentions = list(getattr(context, "location_mentions", None) or [])
    if not mentions:
        return []
    bindings = _resolve_l1_catalog_mentions(
        context,
        mentions,
        evidence_packets=evidence_packets,
        candidate_selection_decisions=candidate_selection_decisions,
    )
    context.grounded_bindings = bindings
    return bindings


__all__ = ["SpatialResolver", "resolve_l1_location_mentions"]
