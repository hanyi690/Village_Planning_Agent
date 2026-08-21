"""Resolve external relation references into bundle-authoritative features.

EvidenceGraph deliberately returns identities and opaque geometry references,
not executable geometry.  This module is the narrow planning-side adapter:
it resolves an ``entity``/``place_hint`` through EvidenceGraph, reads only the
matching feature(s) from the session bundle, and creates an internal
``ScenarioFeature`` for deterministic relation evaluation.

The adapter is bounded and fail-closed.  A named entity with ambiguous
identities, missing bundle geometry, or missing CRS is not converted into a
synthetic point or a geometry copied from the evidence index.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.scenario import ScenarioFeature
from app.contracts.ports.place_resolution_contracts import PlaceResolutionCandidate


_MAX_EXTERNAL_FEATURES = 24
_MAX_UNION_BSMS = 32
_NON_GEOMETRIC_RELATIONS = frozenset({"serve", "service", "precedes"})


@dataclass(frozen=True)
class RelationReferenceResolution:
    """Bounded result of external relation-reference resolution."""

    features: dict[str, ScenarioFeature]
    diagnostics: tuple[str, ...] = ()


def resolve_relation_reference_features(
    context: Any,
    factors: Sequence[ConstraintFactor],
    *,
    scenario_id: str = "reference-context",
) -> RelationReferenceResolution:
    """Resolve non-target relation objects through EvidenceGraph + bundle.

    ``serve`` is excluded because its object is a typed demand snapshot and
    is evaluated by the network service-area subproblem.  All other external
    references require a unique EvidenceGraph identity and authoritative
    bundle geometry before they can influence a spatial relation.
    """

    requests: dict[str, list[str]] = {}
    for factor in sorted(factors, key=lambda item: item.factor_id):
        relation_key = str(factor.evaluator_key or factor.kind or "").strip()
        if relation_key in _NON_GEOMETRIC_RELATIONS:
            continue
        if factor.object_ref_kind == "target":
            continue
        reference = str(factor.object_ref or "").strip()
        if not reference:
            continue
        requests.setdefault(reference, []).append(
            factor.factor_id.removeprefix("factor:")
        )

    if not requests:
        return RelationReferenceResolution(features={})

    graph = getattr(context, "evidence_graph", None)
    workspace = getattr(context, "workspace", None)
    if graph is None or workspace is None:
        return RelationReferenceResolution(
            features={},
            diagnostics=("external_relation_reference_context_unavailable",),
        )

    candidate_rows: dict[str, tuple[list[PlaceResolutionCandidate], list[str]]] = {}
    diagnostics: list[str] = []
    for reference in sorted(requests):
        candidates = _resolve_candidates(graph, reference)
        if not candidates:
            diagnostics.append(f"external_relation_reference_unresolved:{reference}")
            continue
        candidates = _deduplicate_candidates(candidates)
        if len(candidates) != 1:
            diagnostics.append(
                f"external_relation_reference_ambiguous:{reference}:{len(candidates)}"
            )
            continue
        candidate_rows[reference] = (candidates, requests[reference])

    requested_keys: set[str] = set()
    for candidates, _relation_ids in candidate_rows.values():
        requested_keys.update(_candidate_bundle_keys(candidates[0]))
    bundle_features = _index_bundle_features(workspace, requested_keys)

    features: dict[str, ScenarioFeature] = {}
    for reference in sorted(candidate_rows):
        candidates, relation_ids = candidate_rows[reference]
        candidate = candidates[0]
        feature = _feature_from_candidate(
            reference,
            candidate,
            relation_ids=relation_ids,
            bundle_features=bundle_features,
            scenario_id=scenario_id,
            context=context,
        )
        if feature is None:
            diagnostics.append(f"external_relation_bundle_geometry_unavailable:{reference}")
            continue
        features[reference] = feature
        if len(features) >= _MAX_EXTERNAL_FEATURES:
            diagnostics.append("external_relation_reference_bound_reached")
            break

    return RelationReferenceResolution(
        features=features,
        diagnostics=tuple(sorted(dict.fromkeys(diagnostics))),
    )


def _resolve_candidates(graph: Any, reference: str) -> list[PlaceResolutionCandidate]:
    """Resolve an entity URI or typed human reference without guessing."""

    rows: list[PlaceResolutionCandidate] = []
    direct = str(reference).strip()
    suffix = direct.split(":", 1)[1].strip() if ":" in direct else ""
    mentions = [direct]
    if suffix and suffix != direct and not suffix.startswith("//"):
        mentions.append(suffix)

    # Entity refs may be URIs that are not searchable labels.  Check the
    # graph's indexed identities first, then use the normal label resolver.
    for entry in list(getattr(graph, "iter_entries", lambda: [])() or []):
        entity_refs = {str(item).strip() for item in getattr(entry, "entity_refs", []) or []}
        if direct not in entity_refs:
            continue
        rows.append(_candidate_from_entry(entry))

    for mention in mentions:
        try:
            result = graph.resolve_mention(mention, role="unknown")
        except Exception:
            continue
        rows.extend(list(getattr(result, "candidates", []) or []))
        if rows and str(getattr(result, "status", "") or "") == "resolved":
            break
    return rows


def _candidate_from_entry(entry: Any) -> PlaceResolutionCandidate:
    """Convert a private EvidenceGraph entry to its public candidate shape."""

    return PlaceResolutionCandidate(
        entity_ref=str((getattr(entry, "entity_refs", []) or [""])[0] or ""),
        entity_type=str((getattr(entry, "entity_types", []) or [getattr(entry, "role", "unknown")])[0] or "unknown"),
        canonical_name=str(getattr(entry, "canonical_name", "") or ""),
        aliases=list(getattr(entry, "aliases", []) or []),
        geometry_ref=getattr(entry, "geometry_ref", None),
        feature_bsm=getattr(entry, "feature_bsm", None),
        source_feature_id=getattr(entry, "source_feature_id", None),
        source_layer=getattr(entry, "source_layer", None),
        source_bsm=getattr(entry, "source_bsm", None),
        anchor_bsms=list(getattr(entry, "anchor_bsms", []) or []),
        related_parcel_bsms=list(getattr(entry, "related_parcel_bsms", []) or []),
        source_bsms=list(getattr(entry, "source_bsms", []) or []),
        score=float(getattr(entry, "confidence", 0.0) or 0.0),
        evidence_refs=list(getattr(entry, "provenance", []) or []),
        relation_refs=list(getattr(entry, "relation_refs", []) or []),
        l1_fact_refs=list(getattr(entry, "l1_fact_refs", []) or []),
        l1_snapshot_ref=str(getattr(entry, "l1_snapshot_ref", "") or ""),
        bundle_snapshot_digest=str(getattr(entry, "bundle_snapshot_digest", "") or ""),
    )


def _deduplicate_candidates(
    candidates: Iterable[PlaceResolutionCandidate],
) -> list[PlaceResolutionCandidate]:
    rows: dict[tuple[str, str, str], PlaceResolutionCandidate] = {}
    for candidate in candidates:
        key = (
            str(candidate.entity_ref or ""),
            str(candidate.feature_bsm or candidate.source_bsm or ""),
            str(candidate.source_feature_id or ""),
        )
        if key == ("", "", ""):
            continue
        previous = rows.get(key)
        if previous is None or float(candidate.score or 0.0) > float(previous.score or 0.0):
            rows[key] = candidate
    return sorted(rows.values(), key=lambda item: (-float(item.score or 0.0), item.entity_ref))


def _candidate_bundle_keys(candidate: PlaceResolutionCandidate) -> set[str]:
    exact = str(candidate.feature_bsm or candidate.source_bsm or "").strip()
    if exact:
        return {exact}
    source_feature_id = str(candidate.source_feature_id or "").strip()
    if source_feature_id:
        return {f"source_feature_id:{source_feature_id}"}
    entity_type = str(candidate.entity_type or "").strip().lower()
    if entity_type not in {"village", "administrative_village", "residential_cluster", "zone", "parcel"}:
        return set()
    return {
        str(value).strip()
        for value in list(candidate.source_bsms or [])[:_MAX_UNION_BSMS]
        if str(value).strip()
    }


def _index_bundle_features(workspace: Any, requested_keys: set[str]) -> dict[str, list[tuple[str, Any, str]]]:
    """Index only requested bundle identities; geometry is not retained here."""

    result: dict[str, list[tuple[str, Any, str]]] = {}
    if not requested_keys:
        return result
    for group_name in ("points", "lines", "polygons"):
        group = getattr(workspace, group_name, None)
        if group is None or not hasattr(group, "keys"):
            continue
        for layer_name in list(group.keys() or []):
            for feature in list(group.get(layer_name) or []):
                bsm = str(getattr(feature, "bsm", "") or "").strip()
                raw = getattr(feature, "_raw", {}) or {}
                source_feature_id = _source_feature_id(feature)
                keys = {bsm}
                if source_feature_id:
                    keys.add(f"source_feature_id:{source_feature_id}")
                for key in keys & requested_keys:
                    result.setdefault(key, []).append((layer_name, feature, bsm))
    return result


def _feature_from_candidate(
    reference: str,
    candidate: PlaceResolutionCandidate,
    *,
    relation_ids: Sequence[str],
    bundle_features: dict[str, list[tuple[str, Any, str]]],
    scenario_id: str,
    context: Any,
) -> ScenarioFeature | None:
    keys = _candidate_bundle_keys(candidate)
    rows: list[tuple[str, Any, str]] = []
    for key in sorted(keys):
        rows.extend(bundle_features.get(key, []))
    unique: dict[tuple[str, str], tuple[str, Any, str]] = {}
    for layer_name, feature, bsm in rows:
        raw = getattr(feature, "_raw", {}) or {}
        source_feature_id = str(
            raw.get("source_feature_id") if isinstance(raw, dict) else ""
        ).strip()
        unique[(layer_name, bsm or source_feature_id)] = (layer_name, feature, bsm)
    rows = list(unique.values())
    if not rows:
        return None
    source_layer = str(candidate.source_layer or "").strip()
    if source_layer:
        preferred_rows = [row for row in rows if str(row[0]) == source_layer]
        if preferred_rows:
            rows = preferred_rows
    if candidate.feature_bsm or candidate.source_bsm or candidate.source_feature_id:
        rows = rows[:1]
    if len(rows) > _MAX_UNION_BSMS:
        return None

    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        geometries = [shape(getattr(feature, "geometry", None) or {}) for _, feature, _ in rows]
        if any(geometry.is_empty or not geometry.is_valid for geometry in geometries):
            return None
        geometry = geometries[0] if len(geometries) == 1 else unary_union(geometries)
        if geometry.is_empty or not geometry.is_valid:
            return None
        geometry_wkt = geometry.wkt
    except Exception:
        return None

    workspace = getattr(context, "workspace", None)
    crs = str(getattr(getattr(workspace, "metadata", None), "crs", "") or "")
    if not crs:
        return None
    layer_names = sorted({str(row[0]) for row in rows if str(row[0])})
    bsms = sorted({str(row[2]) for row in rows if str(row[2])})
    source_feature_ids = sorted({
        source_feature_id
        for _layer_name, feature, _bsm in rows
        for source_feature_id in [_source_feature_id(feature)]
        if source_feature_id
    })
    raw_key = "|".join([reference, *bsms, *source_feature_ids, *layer_names])
    candidate_id = "reference:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
    kind = _geometry_kind(geometry.geom_type)
    evidence_refs = list(dict.fromkeys([
        *list(candidate.evidence_refs or []),
        *[f"bundle:{layer}:{bsm}" for layer, _feature, bsm in rows if bsm],
    ]))
    return ScenarioFeature(
        feature_id=f"feature:{scenario_id}:{candidate_id}",
        scenario_id=scenario_id or "reference-context",
        target_id=reference,
        candidate_id=candidate_id,
        geometry_kind=kind,
        geometry_wkt=geometry_wkt,
        crs=crs,
        generation_operation="relation_bundle_reference",
        source_refs=evidence_refs or [f"bundle:reference:{reference}"],
        source_bsms=bsms,
        feature_bsms=bsms,
        source_feature_ids=source_feature_ids,
        entity_refs=list(dict.fromkeys([candidate.entity_ref, reference])),
        evidence_refs=evidence_refs,
        l1_fact_refs=list(candidate.l1_fact_refs or []),
        l1_snapshot_ref=str(
            candidate.l1_snapshot_ref
            or getattr(context, "l1_snapshot_ref", "")
            or ""
        ),
        bundle_snapshot_digest=str(
            candidate.bundle_snapshot_digest
            or getattr(getattr(context, "data_snapshot", None), "digest", "")
            or ""
        ),
        relation_ids=sorted(set(str(item) for item in relation_ids if str(item))),
    )


def _geometry_kind(geometry_type: str) -> str:
    value = str(geometry_type or "").lower()
    if value in {"point", "multipoint"}:
        return "point"
    if value in {"linestring", "multilinestring"}:
        return "line"
    if value in {"polygon", "multipolygon"}:
        return "polygon"
    return "multipatch"


def _source_feature_id(feature: Any) -> str:
    raw = getattr(feature, "_raw", {}) or {}
    if isinstance(raw, dict):
        return str(raw.get("source_feature_id") or "").strip()
    return str(getattr(feature, "source_feature_id", "") or "").strip()


__all__ = [
    "RelationReferenceResolution",
    "resolve_relation_reference_features",
]
