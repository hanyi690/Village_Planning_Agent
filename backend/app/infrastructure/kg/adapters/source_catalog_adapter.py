"""Project the generic Data resource catalog into the KG world model."""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping
from functools import lru_cache
from threading import RLock
from typing import Any

from rdflib import Graph, Literal, RDF
from rdflib.namespace import XSD

from app.contracts.cognition.entity import LogicalPartProposal
from app.contracts.data.source_contracts import (
    DataResourceCatalogSnapshot,
    source_local_cognition_ref,
)
from app.infrastructure.kg.ontology import PLN


_RDF_LITERAL = Literal


@lru_cache(maxsize=32768)
def _plain_literal(value: Any) -> Literal:
    """Reuse immutable plain literals during the RDF projection hot path."""

    return _RDF_LITERAL(value)


class _CachedNamespace:
    """Cache ontology predicate lookups without changing URI values."""

    __slots__ = ("_namespace", "_values")

    def __init__(self, namespace: Any) -> None:
        self._namespace = namespace
        self._values: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        value = self._values.get(name)
        if value is None:
            value = getattr(self._namespace, name)
            self._values[name] = value
        return value


_CACHED_PLN = _CachedNamespace(PLN)

_PROJECTION_CACHE_LIMIT = 2
_PROJECTION_CACHE_LOCK = RLock()
_PROJECTION_CACHE: OrderedDict[
    tuple[str, str, str],
    tuple[tuple[tuple[Any, Any, Any], ...], tuple[tuple[Any, Any, Any], ...], int],
] = OrderedDict()

_ANCHOR_CACHE_LIMIT = 8192
_ANCHOR_CACHE_LOCK = RLock()
_ANCHOR_CACHE: OrderedDict[tuple[str, str], tuple[float, float] | None] = OrderedDict()


class _BufferedGraph:
    """Collect one projection transaction and publish it with ``addN``.

    RDFLib's public ``Graph.add`` performs store bookkeeping for every triple.
    Projection is a write-once transaction, so buffering preserves the exact
    graph contents while moving that bookkeeping to one bulk store operation.
    """

    __slots__ = ("_target", "_pending")

    def __init__(self, target: Graph) -> None:
        self._target = target
        self._pending: list[tuple[Any, Any, Any]] = []

    def add(self, triple: tuple[Any, Any, Any]) -> None:
        self._pending.append(triple)

    def flush(self) -> None:
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        self._target.store.addN(
            (subject, predicate, obj, self._target)
            for subject, predicate, obj in pending
        )

    def __iter__(self):
        self.flush()
        return iter(self._target)


def _projection_cache_key(
    snapshot: DataResourceCatalogSnapshot,
    schema_mapping_snapshot: Any,
    *,
    split_graphs: bool,
) -> tuple[str, str, str] | None:
    snapshot_digest = str(getattr(snapshot, "digest", "") or "").strip()
    if not snapshot_digest:
        return None
    mapping_digest = str(
        getattr(schema_mapping_snapshot, "mapping_fingerprint", "")
        or getattr(schema_mapping_snapshot, "decision_fingerprint", "")
        or getattr(schema_mapping_snapshot, "candidate_digest", "")
        or ""
    ).strip()
    if schema_mapping_snapshot is not None and not mapping_digest:
        return None
    return (
        "source-catalog-projection-v1",
        snapshot_digest,
        f"{mapping_digest}:{'split' if split_graphs else 'single'}",
    )


def _replay_projection_cache(
    entry: tuple[tuple[tuple[Any, Any, Any], ...], tuple[tuple[Any, Any, Any], ...], int],
    source_graph: Graph,
    world_graph: Graph | None,
) -> int:
    source_triples, world_triples, projected = entry
    target_graph = world_graph if world_graph is not None else source_graph
    if world_graph is None:
        target_graph.store.addN(
            (subject, predicate, obj, target_graph)
            for subject, predicate, obj in source_triples
        )
        return projected
    source_graph.store.addN(
        (subject, predicate, obj, source_graph)
        for subject, predicate, obj in source_triples
    )
    world_graph.store.addN(
        (subject, predicate, obj, world_graph)
        for subject, predicate, obj in world_triples
    )
    return projected


def _uri(prefix: str, value: str) -> Any:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]
    return PLN[f"{prefix}_{digest}"]


def _decimal_literal(value: float) -> Literal:
    """Keep the normalized coordinate value exact at the RDF boundary."""

    return Literal(str(value), datatype=XSD.decimal)


def _geometry_anchor(
    geometry: Mapping[str, Any] | None,
    *,
    source_crs: str = "",
) -> tuple[float, float] | None:
    """Find a stable WGS84 anchor, normalizing a known source CRS."""

    if not isinstance(geometry, Mapping):
        return None
    coordinates = geometry.get("coordinates")
    transformer = None
    normalized_crs = str(source_crs or "").strip()
    if not normalized_crs:
        return None
    if normalized_crs.casefold() not in {
        "epsg:4326", "4326", "crs84", "urn:ogc:def:crs:ogc:1.3:crs84"
    }:
        try:
            from pyproj import Transformer

            transformer = Transformer.from_crs(
                normalized_crs, "EPSG:4326", always_xy=True
            )
        except Exception:
            return None
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                x, y = float(value[0]), float(value[1])
                if transformer is not None:
                    x, y = transformer.transform(x, y)
                if math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90:
                    points.append((x, y))
                    return
            except (TypeError, ValueError):
                pass
            for child in value:
                visit(child)

    visit(coordinates)
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _feature_geometry(feature: Any) -> tuple[Mapping[str, Any] | None, str]:
    """Use DATA's normalized view whenever it is available.

    World Model identity and co-location indexes operate in WGS84.  Falling
    back to native projected coordinates here would make the same place look
    unrelated (or create invalid lon/lat anchors) after a process restart.
    """

    normalized = getattr(feature, "normalized_geometry", None)
    if isinstance(normalized, Mapping):
        return normalized, "EPSG:4326"
    return (
        getattr(feature, "geometry", None),
        str(getattr(feature, "source_crs", "") or ""),
    )


def _coordinate_support_key(feature: Any) -> str | None:
    """Return a coarse WGS84 key for spatial support, never entity identity."""

    geometry, source_crs = _feature_geometry(feature)
    anchor = _geometry_anchor(geometry, source_crs=source_crs)
    if anchor is None:
        return None
    # 0.0003° is approximately 30 m at village latitudes.  The key is only an
    # indexable co-location hint.  It must never collapse independent source
    # features into one WorldEntity.
    return f"coord:{round(anchor[0] / 0.0003)}:{round(anchor[1] / 0.0003)}"


def _feature_geometry_anchor(feature: Any) -> tuple[float, float] | None:
    """Reuse the deterministic support anchor for repeated WM projections."""

    feature_digest = str(getattr(feature, "source_feature_digest", "") or "")
    geometry, source_crs = _feature_geometry(feature)
    cache_key = (feature_digest, str(source_crs or ""))
    if not feature_digest:
        return _geometry_anchor(geometry, source_crs=source_crs)
    with _ANCHOR_CACHE_LOCK:
        if cache_key in _ANCHOR_CACHE:
            anchor = _ANCHOR_CACHE.pop(cache_key)
            _ANCHOR_CACHE[cache_key] = anchor
            return anchor
    anchor = _geometry_anchor(geometry, source_crs=source_crs)
    with _ANCHOR_CACHE_LOCK:
        _ANCHOR_CACHE[cache_key] = anchor
        _ANCHOR_CACHE.move_to_end(cache_key)
        while len(_ANCHOR_CACHE) > _ANCHOR_CACHE_LIMIT:
            _ANCHOR_CACHE.popitem(last=False)
    return anchor


def _source_identity(feature: Any) -> str:
    claims = dict(getattr(feature, "normalized_claims", {}) or {})
    global_scope = str(
        claims.get("identity_scope") or claims.get("entity_ref_scope") or ""
    ).strip().casefold()
    global_authority = str(
        claims.get("identity_authority")
        or claims.get("entity_ref_authority")
        or ""
    ).strip()
    global_value = (
        claims.get("authoritative_entity_ref")
        or claims.get("entity_ref")
    )
    if (
        global_value not in (None, "", [], {})
        and global_scope in {"global", "authoritative"}
        and global_authority
    ):
        return f"global:{global_authority}:{global_value}"
    source_record_value = claims.get("source_logical_entity_ref")
    if source_record_value not in (None, "", [], {}):
        return source_local_cognition_ref(
            feature.dataset_ref,
            feature.source_feature_ref,
            logical_record_ref=str(source_record_value),
        )
    # A feature without an explicit physical identity is still a legal,
    # unnamed WorldEntity.  Dataset/feature/digest is its source-local stable
    # cognition identity.  Raw BSM/FID/entity-like fields are source claims,
    # never implicit cross-source identity.  Proximity is support-only.
    return source_local_cognition_ref(
        feature.dataset_ref,
        feature.source_feature_ref,
    )


def _semantic_view(schema_mapping_snapshot: Any) -> dict[str, Any]:
    """Index accepted collection decisions without trusting source names."""

    profiles = tuple(
        getattr(schema_mapping_snapshot, "collection_profiles", ()) or ()
    )
    decisions = tuple(getattr(schema_mapping_snapshot, "decisions", ()) or ())
    profile_by_ref = {
        str(getattr(profile, "collection_ref", "")): profile
        for profile in profiles
    }
    view: dict[str, Any] = {
        "collection_ref": {},
        "concept": {},
        "representation_role": {},
        "properties": {},
        "decision_refs": {},
        "status": {},
    }
    for profile in profiles:
        key = (
            str(getattr(profile, "dataset_ref", "") or ""),
            str(getattr(profile, "layer_ref", "") or ""),
        )
        view["collection_ref"][key] = str(
            getattr(profile, "collection_ref", "") or ""
        )
    for decision in decisions:
        collection_ref = str(getattr(decision, "collection_ref", "") or "")
        profile = profile_by_ref.get(collection_ref)
        if profile is None:
            continue
        key = (
            str(getattr(profile, "dataset_ref", "") or ""),
            str(getattr(profile, "layer_ref", "") or ""),
        )
        field_name = str(getattr(decision, "field_name", "") or "")
        status = str(getattr(decision, "status", "") or "unresolved")
        view["status"][(key, field_name)] = status
        decision_ref = str(getattr(decision, "decision_ref", "") or "")
        if decision_ref:
            view["decision_refs"].setdefault(key, []).append(decision_ref)
        if status != "accepted":
            continue
        concept = str(getattr(decision, "candidate_concept_ref", "") or "")
        role = str(getattr(decision, "representation_role_ref", "") or "")
        property_ref = str(
            getattr(decision, "candidate_property_ref", "") or ""
        )
        if concept:
            view["concept"][key] = concept
        if role:
            geometry_kind = field_name.partition(":")[2].casefold()
            view["representation_role"][(key, geometry_kind)] = role
        if property_ref and field_name:
            view["properties"].setdefault(key, {}).setdefault(
                property_ref,
                [],
            ).append(field_name)
    return view


def _feature_key(feature: Any) -> tuple[str, str]:
    return (
        str(getattr(feature, "dataset_ref", "") or ""),
        str(getattr(feature, "layer_ref", "") or ""),
    )


def _source_feature_key(
    dataset_ref: Any,
    source_feature_ref: Any,
) -> tuple[str, str]:
    """Return the only safe in-memory key for a source feature."""

    return (str(dataset_ref or ""), str(source_feature_ref or ""))


def _qualified_source_feature_ref(feature: Any) -> str:
    return (
        f"resource:{getattr(feature, 'dataset_ref', '')}:"
        f"{getattr(feature, 'source_feature_ref', '')}"
    )


def _representation_source_key(representation: Any) -> tuple[str, str]:
    dataset_ref = str(getattr(representation, "dataset_ref", "") or "")
    source_feature_ref = str(
        getattr(representation, "source_feature_ref", "") or ""
    )
    if not dataset_ref:
        resource_ref = str(getattr(representation, "resource_ref", "") or "")
        if resource_ref.startswith("resource:"):
            payload = resource_ref[len("resource:"):]
            dataset_ref, separator, parsed_feature_ref = payload.rpartition(":")
            if separator and parsed_feature_ref == source_feature_ref:
                return _source_feature_key(dataset_ref, source_feature_ref)
    return _source_feature_key(dataset_ref, source_feature_ref)


def _accepted_values(
    feature: Any,
    semantic_view: Mapping[str, Any],
    property_ref: str,
) -> set[str]:
    fields = (
        semantic_view.get("properties", {})
        .get(_feature_key(feature), {})
        .get(property_ref, ())
    )
    attributes = dict(getattr(feature, "raw_attributes", {}) or {})
    return {
        str(attributes[field]).strip()
        for field in fields
        if attributes.get(field) not in (None, "", [], {}, ())
    }


def _line_endpoints(feature: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    geometry, source_crs = _feature_geometry(feature)
    geometry = geometry if isinstance(geometry, Mapping) else None
    geometry_type = str((geometry or {}).get("type") or "").casefold()
    if geometry_type not in {"linestring", "multilinestring"}:
        return None
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "multilinestring":
        lines = [
            line
            for line in coordinates
            if isinstance(line, (list, tuple)) and len(line) >= 2
        ]
        if not lines:
            return None
        coordinates = [lines[0][0], lines[-1][-1]]
    if len(coordinates) < 2:
        return None
    transformer = None
    normalized_crs = str(source_crs or "").strip()
    if not normalized_crs:
        return None
    if normalized_crs.casefold() not in {
        "epsg:4326", "4326", "crs84", "urn:ogc:def:crs:ogc:1.3:crs84"
    }:
        try:
            from pyproj import Transformer

            transformer = Transformer.from_crs(
                normalized_crs, "EPSG:4326", always_xy=True
            )
        except Exception:
            return None
    try:
        first = (float(coordinates[0][0]), float(coordinates[0][1]))
        last = (float(coordinates[-1][0]), float(coordinates[-1][1]))
        if transformer is not None:
            first = tuple(float(value) for value in transformer.transform(*first))
            last = tuple(float(value) for value in transformer.transform(*last))
    except (TypeError, ValueError, IndexError):
        return None
    return first, last


def _line_component_identities(
    features: list[Any],
    semantic_view: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    """Group connected line segments only through accepted semantics."""

    def semantic_tokens(feature: Any) -> set[str]:
        concept = str(
            semantic_view.get("concept", {}).get(_feature_key(feature), "")
            or ""
        )
        if concept not in {"road", "watercourse", "linear_feature"}:
            return set()
        return {
            value.casefold()
            for value in _accepted_values(
                feature,
                semantic_view,
                "canonical_name",
            )
            if value
        }

    indexed = []
    for index, feature in enumerate(features):
        endpoints = _line_endpoints(feature)
        if endpoints is not None:
            indexed.append((index, feature, endpoints))
    parent = {index: index for index, _, _ in indexed}
    endpoints_by_index = {
        index: endpoints for index, _feature, endpoints in indexed
    }
    tokens_by_index = {
        index: semantic_tokens(feature)
        for index, feature, _endpoints in indexed
    }

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    tolerance = 0.0003
    # Candidate pairs are found through a fixed-size endpoint grid.  The
    # exact distance check below is unchanged; the grid only removes pairs
    # that cannot possibly be within ``tolerance``.  Tokens are also computed
    # once per feature instead of once per quadratic pair.
    cell_size = tolerance
    endpoint_grid: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = {}

    def cell(point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(point[0] // cell_size),
            int(point[1] // cell_size),
        )

    for index, _feature, endpoints in indexed:
        for point in endpoints:
            endpoint_grid.setdefault(cell(point), []).append((index, point))

    candidate_pairs: set[tuple[int, int]] = set()
    for left, _feature, endpoints_left in indexed:
        tokens_left = tokens_by_index[left]
        if not tokens_left:
            continue
        for point in endpoints_left:
            point_cell = cell(point)
            for delta_x in (-1, 0, 1):
                for delta_y in (-1, 0, 1):
                    for right, _other_point in endpoint_grid.get(
                        (point_cell[0] + delta_x, point_cell[1] + delta_y),
                        (),
                    ):
                        if right > left:
                            candidate_pairs.add((left, right))

    for left, right in sorted(candidate_pairs):
        tokens_left = tokens_by_index[left]
        tokens_right = tokens_by_index[right]
        if not tokens_left.intersection(tokens_right):
            continue
        endpoints_left = endpoints_by_index[left]
        endpoints_right = endpoints_by_index[right]
        if any(
            (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 <= tolerance ** 2
            for a in endpoints_left
            for b in endpoints_right
        ):
            union(left, right)
    components: dict[int, list[Any]] = {}
    for index, feature, _endpoints in indexed:
        components.setdefault(find(index), []).append(feature)
    result: dict[tuple[str, str], str] = {}
    for members in components.values():
        if len(members) < 2:
            continue
        material = sorted(
            f"{item.dataset_ref}|{item.source_feature_ref}"
            for item in members
        )
        component_digest = hashlib.sha256(
            "\n".join(material).encode("utf-8")
        ).hexdigest()[:24]
        identity = f"line_component:{component_digest}"
        for feature in members:
            result[_source_feature_key(
                feature.dataset_ref,
                feature.source_feature_ref,
            )] = identity
    return result


def _part_identity(feature: Any) -> str:
    claims = dict(getattr(feature, "normalized_claims", {}) or {})
    for key in (
        "authoritative_part_ref",
        "entity_part_ref",
        "source_logical_part_ref",
    ):
        value = claims.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return str(feature.source_feature_ref)


def _representation_kind(feature: Any) -> str:
    """Return the normalized kind used by current-world consumers."""

    normalized = str(
        getattr(feature, "normalized_geometry_kind", "") or ""
    ).casefold()
    if normalized and normalized != "unknown":
        return normalized
    normalized_geometry = getattr(feature, "normalized_geometry", None)
    if isinstance(normalized_geometry, dict):
        inferred = {
            "point": "point",
            "multipoint": "point",
            "linestring": "line",
            "multilinestring": "line",
            "polygon": "polygon",
            "multipolygon": "polygon",
            "geometrycollection": "collection",
        }.get(str(normalized_geometry.get("type") or "").casefold(), "")
        if inferred:
            return inferred
    return str(getattr(feature, "geometry_kind", "") or "").casefold()


def project_source_catalog(
    graph: Graph,
    catalog: Any,
    *,
    world_graph: Graph | None = None,
    schema_mapping_snapshot: Any = None,
) -> int:
    """Add source-backed WorldEntity/Representation nodes without fixed layers."""

    # Terms created below are immutable; reuse repeated literals and ontology
    # predicates while leaving the external RDFLib Graph contract untouched.
    Literal = _plain_literal
    PLN = _CACHED_PLN
    snapshot = getattr(catalog, "snapshot", catalog)
    if not isinstance(snapshot, DataResourceCatalogSnapshot):
        raise TypeError("catalog must expose a DataResourceCatalogSnapshot")
    from app.data.admission import assert_cognition_ready_catalog

    assert_cognition_ready_catalog(snapshot)
    split_graphs = world_graph is not None and world_graph is not graph
    cache_key = _projection_cache_key(
        snapshot,
        schema_mapping_snapshot,
        split_graphs=split_graphs,
    )
    if cache_key is not None:
        with _PROJECTION_CACHE_LOCK:
            cached_entry = _PROJECTION_CACHE.get(cache_key)
            if cached_entry is not None:
                _PROJECTION_CACHE.move_to_end(cache_key)
        if cached_entry is not None:
            return _replay_projection_cache(
                cached_entry,
                graph,
                world_graph if split_graphs else None,
            )
    source_existing = frozenset(graph)
    world_existing = (
        frozenset(world_graph)
        if split_graphs and world_graph is not None
        else frozenset()
    )
    source_graph = _BufferedGraph(graph)
    world_buffer = (
        _BufferedGraph(world_graph)
        if split_graphs and world_graph is not None
        else source_graph
    )
    graph = source_graph
    semantic_view = _semantic_view(schema_mapping_snapshot)
    datasets = tuple(snapshot.datasets or (snapshot.dataset,))
    dataset_nodes: dict[str, Any] = {}
    for dataset in datasets:
        node = _uri("dataset", dataset.dataset_ref)
        dataset_nodes[dataset.dataset_ref] = node
        graph.add((node, RDF.type, PLN.SourceDataset))
        graph.add((node, PLN.datasetRef, Literal(dataset.dataset_ref)))
        if dataset.name:
            graph.add((node, PLN.name, Literal(dataset.name)))
        if dataset.version:
            graph.add((node, PLN.version, Literal(dataset.version)))
        graph.add((node, PLN.crs, Literal(dataset.crs)))
        graph.add((node, PLN.contentDigest, Literal(dataset.digest)))
        graph.add((node, PLN.featureCount, Literal(dataset.feature_count)))
        for uri in dataset.source_uris:
            graph.add((node, PLN.sourceUri, Literal(uri)))
    # Executable capabilities remain authoritative in DATA. Materializing one
    # disconnected RDF node per resource/operation inflated a village graph by
    # hundreds of thousands of triples without adding entity cognition or a
    # query path. GROUND/SELECT/EXECUTE resolve capabilities through the
    # catalog's typed lookup API and keep only selected capability refs in
    # their lineage artifacts.
    source_record_nodes: dict[tuple[str, str], Any] = {}
    for feature in snapshot.features:
        source_record = _uri(
            "source_record",
            f"{feature.dataset_ref}:{feature.source_feature_ref}",
        )
        source_record_nodes[_source_feature_key(
            feature.dataset_ref,
            feature.source_feature_ref,
        )] = source_record
        graph.add((source_record, RDF.type, PLN.SourceRecord))
        graph.add((source_record, PLN.sourceFeatureRef, Literal(feature.source_feature_ref)))
        graph.add((source_record, PLN.sourceFeatureDigest, Literal(feature.source_feature_digest)))
        graph.add((source_record, PLN.sourceDatasetRef, Literal(feature.dataset_ref)))
        graph.add((source_record, PLN.sourceSnapshotRef, Literal(snapshot.snapshot_id)))
        dataset_node = dataset_nodes.get(feature.dataset_ref)
        if dataset_node is not None:
            graph.add((source_record, PLN.sourceDataset, dataset_node))
        if feature.layer_ref:
            graph.add((source_record, PLN.sourceLayerRef, Literal(feature.layer_ref)))
        collection_ref = str(
            semantic_view.get("collection_ref", {}).get(_feature_key(feature), "")
            or ""
        )
        if collection_ref:
            graph.add((
                source_record,
                PLN.sourceCollectionRef,
                Literal(collection_ref),
            ))
        if feature.source_crs:
            graph.add((source_record, PLN.sourceCrs, Literal(feature.source_crs)))
        if feature.normalized_crs:
            graph.add((source_record, PLN.normalizedCrs, Literal(feature.normalized_crs)))
        graph.add((source_record, PLN.geometryKind, Literal(feature.geometry_kind)))

    spatial_features = [
        feature
        for feature in snapshot.features
        if _representation_kind(feature)
        in {"point", "line", "polygon", "multipatch", "collection"}
    ]
    graph = world_buffer
    representation_by_feature: dict[tuple[str, str], list[Any]] = {}
    for representation in snapshot.representations:
        representation_by_feature.setdefault(
            _representation_source_key(representation),
            [],
        ).append(representation)
    groups: dict[str, list[Any]] = {}
    line_components = _line_component_identities(spatial_features, semantic_view)
    feature_identities: dict[int, str] = {}
    for feature in spatial_features:
        identity = line_components.get(
            _source_feature_key(feature.dataset_ref, feature.source_feature_ref),
            _source_identity(feature),
        )
        groups.setdefault(identity, []).append(feature)
        feature_identities[id(feature)] = identity
    projected = 0
    for identity, group in groups.items():
        entity = _uri("world_entity", identity)
        graph.add((entity, RDF.type, PLN.WorldEntity))
        graph.add((entity, PLN.entityIdentity, Literal(identity)))
        labels = {
            value
            for feature in group
            for property_ref in ("canonical_name", "observed_label")
            for value in _accepted_values(feature, semantic_view, property_ref)
        }
        if labels:
            canonical = sorted(labels)[0]
            graph.add((entity, PLN.canonicalName, Literal(canonical)))
            for label in sorted(labels):
                graph.add((entity, PLN.alias, Literal(label)))
        concept_values = {
            str(semantic_view.get("concept", {}).get(_feature_key(feature), ""))
            for feature in group
            if str(semantic_view.get("concept", {}).get(_feature_key(feature), ""))
        }
        for concept in sorted(concept_values):
            graph.add((entity, PLN.conceptType, Literal(concept)))
        # Existence and semantic classification are different axes.  Every
        # admitted spatial observation creates a legal source-local entity;
        # missing names or authoritative IDs never make that entity absent.
        graph.add((entity, PLN.entityStatus, Literal("observed")))
        identity_status = (
            "accepted"
            if identity.startswith("global:") or identity.startswith("line_component:")
            else "source_local"
        )
        graph.add((entity, PLN.identityResolutionStatus, Literal(identity_status)))
        semantic_status = "accepted" if concept_values else "unresolved"
        graph.add((entity, PLN.semanticStatus, Literal(semantic_status)))
        for feature in group:
            for decision_ref in semantic_view.get("decision_refs", {}).get(
                _feature_key(feature),
                (),
            ):
                graph.add((entity, PLN.schemaDecisionRef, Literal(decision_ref)))
        for feature in group:
            part = _uri("entity_part", f"{identity}:{_part_identity(feature)}")
            graph.add((entity, PLN.hasEntityPart, part))
            graph.add((part, RDF.type, PLN.EntityPart))
            graph.add((part, PLN.partIdentity, Literal(_part_identity(feature))))
            graph.add((part, PLN.sourceFeatureRef, Literal(feature.source_feature_ref)))
            graph.add((
                part,
                PLN.sourceResourceRef,
                Literal(_qualified_source_feature_ref(feature)),
            ))
            source_key = _source_feature_key(
                feature.dataset_ref,
                feature.source_feature_ref,
            )
            source_record = source_record_nodes.get(source_key)
            if source_record is not None:
                graph.add((part, PLN.describedBySourceRecord, source_record))
            graph.add((part, PLN.sourceDatasetRef, Literal(feature.dataset_ref)))
            dataset_node = dataset_nodes.get(feature.dataset_ref)
            if dataset_node is not None:
                graph.add((part, PLN.sourceDataset, dataset_node))
            if feature.layer_ref:
                graph.add((part, PLN.sourceLayerRef, Literal(feature.layer_ref)))
            graph.add((part, PLN.geometryKind, Literal(_representation_kind(feature))))
            graph.add((part, PLN.sourceFeatureDigest, Literal(feature.source_feature_digest)))
            graph.add((part, PLN.sourceCrs, Literal(getattr(feature, "source_crs", "") or "")))
            graph.add((part, PLN.normalizedCrs, Literal(getattr(feature, "normalized_crs", "") or "")))
            graph.add((part, PLN.sourceSnapshotRef, Literal(getattr(snapshot, "snapshot_id", "") or "")))
            for transform in getattr(feature, "crs_transform", ()) or ():
                graph.add((part, PLN.crsTransform, Literal(str(transform))))
            # Lossless physical fields stay in DATA and are addressed through
            # this part's sourceResourceRef. Normalized source claims also
            # stay in SOURCE_GRAPH: they describe what DATA admitted, not a
            # Cognition-approved world fact. Only a later decision transaction
            # may create a SemanticAssertion in ASSERTION_GRAPH.
            for key, value in sorted((feature.normalized_claims or {}).items(), key=lambda item: str(item[0])):
                if value in (None, "", [], {}):
                    continue
                claim = _uri(
                    "normalized_claim",
                    f"{feature.dataset_ref}:{feature.source_feature_ref}:{key}",
                )
                source_graph.add((source_record, PLN.hasNormalizedSourceClaim, claim))
                source_graph.add((claim, RDF.type, PLN.NormalizedSourceClaim))
                source_graph.add((claim, PLN.sourceFeatureRef, Literal(feature.source_feature_ref)))
                source_graph.add((claim, PLN.sourceDatasetRef, Literal(feature.dataset_ref)))
                source_graph.add((claim, PLN.sourceSnapshotRef, Literal(snapshot.snapshot_id)))
                source_graph.add((claim, PLN.sourceFeatureDigest, Literal(feature.source_feature_digest)))
                source_graph.add((claim, PLN.claimKey, Literal(str(key))))
                source_graph.add((claim, PLN.claimValue, Literal(str(value))))
            for representation in representation_by_feature.get(source_key, []):
                rep_node = _uri("representation", representation.representation_ref)
                graph.add((part, PLN.hasSpatialRepresentation, rep_node))
                graph.add((rep_node, RDF.type, PLN.SpatialRepresentation))
                graph.add((rep_node, PLN.representationRef, Literal(representation.representation_ref)))
                graph.add((rep_node, PLN.sourceFeatureRef, Literal(feature.source_feature_ref)))
                graph.add((rep_node, PLN.sourceDatasetRef, Literal(feature.dataset_ref)))
                graph.add((rep_node, PLN.sourceFeatureDigest, Literal(feature.source_feature_digest)))
                if source_record is not None:
                    graph.add((rep_node, PLN.derivedFromSourceRecord, source_record))
                # The DATA adapter may only know a provisional feature
                # identity.  The KG grouping pass records the current
                # source-backed cognition identity (including semantically
                # compatible connected road segments); coordinate proximity
                # remains support-only and never changes this identity.
                graph.add((rep_node, PLN.entityRef, Literal(identity)))
                source_purpose = str(representation.purpose or "")
                if source_purpose:
                    graph.add((
                        rep_node,
                        PLN.sourceRepresentationPurpose,
                        Literal(source_purpose),
                    ))
                accepted_purpose = str(
                    semantic_view.get("representation_role", {}).get(
                        (
                            _feature_key(feature),
                            _representation_kind(feature),
                        ),
                        "",
                    )
                    or ""
                )
                if accepted_purpose:
                    graph.add((
                        rep_node,
                        PLN.representationPurpose,
                        Literal(accepted_purpose),
                    ))
                    graph.add((
                        rep_node,
                        PLN.representationSemanticStatus,
                        Literal("accepted"),
                    ))
                else:
                    graph.add((
                        rep_node,
                        PLN.representationSemanticStatus,
                        Literal("unresolved"),
                    ))
                graph.add((rep_node, PLN.resourceRef, Literal(representation.resource_ref)))
                graph.add((rep_node, PLN.geometryRef, Literal(representation.geometry_ref)))
                graph.add((rep_node, PLN.geometryKind, Literal(representation.geometry_kind)))
                graph.add((rep_node, PLN.crs, Literal(representation.crs)))
                graph.add((rep_node, PLN.sourceCrs, Literal(getattr(representation, "source_crs", "") or "")))
                graph.add((rep_node, PLN.normalizedCrs, Literal(getattr(representation, "normalized_crs", "") or representation.crs)))
                for transform in getattr(representation, "crs_transform", ()) or ():
                    graph.add((rep_node, PLN.crsTransform, Literal(str(transform))))
                graph.add((rep_node, PLN.sourceSnapshotRef, Literal(getattr(representation, "source_snapshot_ref", "") or getattr(snapshot, "snapshot_id", "") or "")))
                graph.add((rep_node, PLN.contentDigest, Literal(representation.content_digest)))
            projected += 1
        # Connected line records describe one physical road WorldEntity and
        # independently operable EntityParts.  The parts were already created
        # from the source records above; do not promote the same segment to a
        # second WorldEntity.  A derived multi-line representation keeps only
        # component refs, so geometry still resolves through DATA.
        if len(group) > 1 and all(
            _representation_kind(item) == "line"
            for item in group
        ):
            derived_part = _uri("entity_part", f"{identity}:derived_centerline")
            derived_rep = _uri("derived_representation", identity)
            graph.add((entity, PLN.hasEntityPart, derived_part))
            graph.add((derived_part, RDF.type, PLN.EntityPart))
            graph.add((derived_part, PLN.geometryKind, Literal("line")))
            graph.add((derived_part, PLN.hasSpatialRepresentation, derived_rep))
            graph.add((derived_rep, RDF.type, PLN.SpatialRepresentation))
            graph.add((derived_rep, PLN.representationRef, Literal(f"representation:{identity}:derived_centerline")))
            graph.add((derived_rep, PLN.entityRef, Literal(identity)))
            graph.add((derived_rep, PLN.representationPurpose, Literal("derived_centerline")))
            graph.add((derived_rep, PLN.geometryKind, Literal("line")))
            graph.add((derived_rep, PLN.derivedFrom, Literal("component_refs")))
            component_representations = [
                representation
                for feature in group
                for representation in representation_by_feature.get(
                    _source_feature_key(
                        feature.dataset_ref,
                        feature.source_feature_ref,
                    ),
                    (),
                )
            ]
            component_manifest = sorted(
                f"{item.representation_ref}|{item.content_digest}"
                for item in component_representations
            )
            if component_manifest:
                graph.add((
                    derived_rep,
                    PLN.contentDigest,
                    Literal(
                        "sha256:"
                        + hashlib.sha256(
                            "\n".join(component_manifest).encode("utf-8")
                        ).hexdigest()
                    ),
                ))
            crs_values = {
                str(item.crs)
                for item in component_representations
                if str(item.crs).strip()
            }
            if len(crs_values) == 1:
                graph.add((derived_rep, PLN.crs, Literal(next(iter(crs_values)))))
            snapshot_refs = {
                str(item.source_snapshot_ref)
                for item in component_representations
                if str(item.source_snapshot_ref).strip()
            }
            if len(snapshot_refs) == 1:
                graph.add((
                    derived_rep,
                    PLN.sourceSnapshotRef,
                    Literal(next(iter(snapshot_refs))),
                ))
            for feature in group:
                graph.add((
                    derived_rep,
                    PLN.componentRef,
                    Literal(_qualified_source_feature_ref(feature)),
                ))
                for representation in representation_by_feature.get(
                    _source_feature_key(
                        feature.dataset_ref,
                        feature.source_feature_ref,
                    ),
                    (),
                ):
                    graph.add((
                        derived_rep,
                        PLN.componentRepresentationRef,
                        Literal(representation.representation_ref),
                    ))
    # Co-location support is deliberately projected after entity grouping.
    # It lets retrieval explain why two observations are near one another
    # without asserting that they are the same physical entity.  The support
    # node has no geometry/resource authority and is therefore ignored by the
    # executable GROUND/SELECT paths.
    # Use a small spatial hash plus an exact tolerance check.  Quantizing each
    # point independently can put two points on opposite sides of a cell
    # boundary even when they are only a few metres apart; the neighbour-cell
    # pass keeps co-location support deterministic without merging entities.
    tolerance = 0.0003
    anchored: list[tuple[Any, str, tuple[float, float]]] = []
    for feature in spatial_features:
        identity = feature_identities.get(id(feature), "")
        anchor = _feature_geometry_anchor(feature)
        if identity and anchor is not None:
            anchored.append((feature, identity, anchor))
    cells: dict[tuple[int, int], list[int]] = {}
    for index, (_feature, _identity, anchor) in enumerate(anchored):
        cell = (math.floor(anchor[0] / tolerance), math.floor(anchor[1] / tolerance))
        cells.setdefault(cell, []).append(index)
    parent = list(range(len(anchored)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for index, (_feature, _identity, anchor) in enumerate(anchored):
        cell_x = math.floor(anchor[0] / tolerance)
        cell_y = math.floor(anchor[1] / tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in cells.get((cell_x + dx, cell_y + dy), []):
                    if other <= index:
                        continue
                    other_anchor = anchored[other][2]
                    if (
                        (anchor[0] - other_anchor[0]) ** 2
                        + (anchor[1] - other_anchor[1]) ** 2
                        <= tolerance ** 2
                    ):
                        union(index, other)
    support_groups: dict[int, list[tuple[Any, str, tuple[float, float]]]] = {}
    for index, item in enumerate(anchored):
        support_groups.setdefault(find(index), []).append(item)
    for members in sorted(
        support_groups.values(),
        key=lambda values: tuple(sorted(item[1] for item in values)),
    ):
        identities = sorted({identity for _feature, identity, _anchor in members})
        if len(identities) < 2:
            continue
        source_refs = sorted(
            _qualified_source_feature_ref(feature)
            for feature, _identity, _anchor in members
        )
        support_digest = hashlib.sha256(
            "\n".join(source_refs).encode("utf-8")
        ).hexdigest()[:24]
        support_key = f"coordinate_support:{support_digest}"
        cluster_id = f"{support_key}:{'|'.join(identities)}"
        cluster = _uri("spatial_support_cluster", cluster_id)
        graph.add((cluster, RDF.type, PLN.SpatialSupportCluster))
        graph.add((cluster, PLN.supportKey, Literal(support_key)))
        graph.add((cluster, PLN.supportReason, Literal("coordinate_proximity")))
        graph.add((
            cluster,
            PLN.supportAlgorithmVersion,
            Literal("wgs84-anchor-mean-radius-v1"),
        ))
        graph.add((
            cluster,
            PLN.supportToleranceDegrees,
            _decimal_literal(tolerance),
        ))
        graph.add((
            cluster,
            PLN.sourceSnapshotRef,
            Literal(str(getattr(snapshot, "snapshot_id", "") or "")),
        ))
        graph.add((
            cluster,
            PLN.sourceCatalogDigest,
            Literal(str(getattr(snapshot, "digest", "") or "")),
        ))
        for feature, identity, anchor in members:
            source_ref = _qualified_source_feature_ref(feature)
            evidence_node = _uri(
                "spatial_support_evidence",
                f"{support_key}:{source_ref}:{feature.source_feature_digest}",
            )
            graph.add((cluster, PLN.hasSupportEvidence, evidence_node))
            graph.add((evidence_node, RDF.type, PLN.SpatialSupportEvidence))
            graph.add((evidence_node, PLN.sourceResourceRef, Literal(source_ref)))
            graph.add((
                evidence_node,
                PLN.sourceFeatureDigest,
                Literal(feature.source_feature_digest),
            ))
            graph.add((evidence_node, PLN.sourceDatasetRef, Literal(feature.dataset_ref)))
            graph.add((evidence_node, PLN.sourceFeatureRef, Literal(feature.source_feature_ref)))
            graph.add((
                evidence_node,
                PLN.supportAnchorX,
                _decimal_literal(anchor[0]),
            ))
            graph.add((
                evidence_node,
                PLN.supportAnchorY,
                _decimal_literal(anchor[1]),
            ))
            graph.add((evidence_node, PLN.supportEntityIdentity, Literal(identity)))
        for identity in identities:
            graph.add((cluster, PLN.supports_entity, _uri("world_entity", identity)))
            graph.add((cluster, PLN.supportEntityIdentity, Literal(identity)))
    source_graph.flush()
    if split_graphs and world_graph is not None:
        graph.flush()
    if cache_key is not None:
        source_triples = tuple(
            triple for triple in source_graph if triple not in source_existing
        )
        world_triples = (
            tuple(triple for triple in graph if triple not in world_existing)
            if split_graphs
            else ()
        )
        entry = (source_triples, world_triples, projected)
        with _PROJECTION_CACHE_LOCK:
            _PROJECTION_CACHE[cache_key] = entry
            _PROJECTION_CACHE.move_to_end(cache_key)
            while len(_PROJECTION_CACHE) > _PROJECTION_CACHE_LIMIT:
                _PROJECTION_CACHE.popitem(last=False)
    return projected


def build_logical_part_proposals(
    catalog: Any,
    *,
    entity_refs: tuple[str, ...] | list[str] | None = None,
    large_entity_refs: tuple[str, ...] | list[str] = (),
    constraint_refs: tuple[str, ...] | list[str] = (),
    operation_refs: tuple[str, ...] | list[str] = (),
) -> tuple[LogicalPartProposal, ...]:
    """Build geometry-free logical-part proposals from a DATA snapshot.

    The adapter intentionally does not split polygons, calculate centroids or
    copy coordinates.  It groups source features using the same source-scoped
    identity and part hints as :func:`project_source_catalog`, then references
    the already-published DATA representations.  A caller may mark an entity
    as ``large_entity_refs`` when a deterministic area/extent policy (owned by
    DATA or L2) says that the whole extent needs a target-time split decision.
    """

    snapshot = getattr(catalog, "snapshot", catalog)
    if not isinstance(snapshot, DataResourceCatalogSnapshot):
        raise TypeError("catalog must expose a DataResourceCatalogSnapshot")
    requested = {
        str(value).strip()
        for value in (entity_refs or ())
        if str(value).strip()
    }
    large = {
        str(value).strip()
        for value in large_entity_refs
        if str(value).strip()
    }
    shared_constraints = tuple(sorted({
        str(value).strip()
        for value in constraint_refs
        if str(value).strip()
    }))
    shared_operations = tuple(sorted({
        str(value).strip()
        for value in operation_refs
        if str(value).strip()
    }))
    representations_by_feature: dict[tuple[str, str], list[Any]] = {}
    for representation in snapshot.representations:
        representations_by_feature.setdefault(
            _representation_source_key(representation),
            [],
        ).append(representation)

    # Keep the grouping aligned with KG projection, while making no inference
    # from a layer name or a business field such as BSM/DLBM.
    groups: dict[str, list[Any]] = {}
    for feature in snapshot.features:
        if _representation_kind(feature) not in {
            "polygon",
            "multipatch",
        }:
            continue
        identity = _source_identity(feature)
        if requested and identity not in requested:
            continue
        groups.setdefault(identity, []).append(feature)

    proposals: list[LogicalPartProposal] = []
    for identity, features in sorted(groups.items(), key=lambda item: item[0]):
        part_groups: dict[str, list[Any]] = {}
        for feature in features:
            part_groups.setdefault(_part_identity(feature), []).append(feature)
        for part_identity, part_features in sorted(part_groups.items(), key=lambda item: item[0]):
            source_feature_refs = tuple(sorted({
                str(feature.source_feature_ref)
                for feature in part_features
                if str(feature.source_feature_ref).strip()
            }))
            source_record_refs = tuple(sorted({
                _qualified_source_feature_ref(feature)
                for feature in part_features
            }))
            representation_refs = tuple(sorted({
                str(representation.representation_ref)
                for feature in part_features
                for representation in representations_by_feature.get(
                    _source_feature_key(
                        feature.dataset_ref,
                        feature.source_feature_ref,
                    ),
                    (),
                )
                if str(representation.representation_ref).strip()
            }))
            part_ref = str(_uri("entity_part", f"{identity}:{part_identity}"))
            large_hint = identity in large or any(
                ref in large
                for ref in (*source_feature_refs, *source_record_refs)
            )
            material = {
                "entity_ref": identity,
                "part_ref": part_ref,
                "source_record_refs": source_record_refs,
                "source_feature_refs": source_feature_refs,
                "representation_refs": representation_refs,
                "constraint_refs": shared_constraints,
                "operation_refs": shared_operations,
                "large_entity_hint": large_hint,
            }
            proposal_ref = "logical-part-proposal:" + hashlib.sha256(
                json.dumps(
                    material,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:24]
            proposals.append(
                LogicalPartProposal(
                    proposal_ref=proposal_ref,
                    entity_ref=identity,
                    part_ref=part_ref,
                    source_record_refs=source_record_refs,
                    source_feature_refs=source_feature_refs,
                    representation_refs=representation_refs,
                    constraint_refs=shared_constraints,
                    operation_refs=shared_operations,
                    large_entity_hint=large_hint,
                    status="candidate",
                    confidence=0.25 if large_hint else 0.5,
                    reason=(
                        "large source extent retained; target constraints and "
                        "operation scope must decide whether to split"
                        if large_hint
                        else "source logical part retained; no geometry synthesized"
                    ),
                )
            )
    return tuple(proposals)


# Short alias for callers that use the domain wording from the design
# document.  Both names are pure DATA/KG adapters.
propose_logical_parts = build_logical_part_proposals


__all__ = [
    "build_logical_part_proposals",
    "project_source_catalog",
    "propose_logical_parts",
]
