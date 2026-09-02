"""Evidence retrieval over the DATA-backed World Model port.

This path is intentionally small and deterministic.  It returns candidate
rows and provenance; it never treats an external observation as executable
geometry and never fabricates a missing source feature.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
    SpatialCognitionEvidence,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.feature_identity_contracts import (
    FeatureEvidenceRef,
    SourceFeatureIdentity,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.evidence.external_observation_contracts import (
    is_wgs84_equivalent_crs,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


_LOCAL_SOURCE_FAMILIES = frozenset({
    "artifact", "bundle", "data", "gis", "kg", "local_data",
})
_EXTERNAL_SOURCE_FAMILIES = frozenset({
    "external", "external_map_cache", "map_cache",
})
_UNIQUE_BINDING_ROLES = frozenset({
    "location_binding",
    "grounding_candidate_resolution",
    "target_pending_grounding",
    "target_spatial_binding",
})
_EXTERNAL_CANDIDATES_PER_CLUSTER = 8


def _allows_source(
    requirement: EvidenceRequirement,
    allowed: frozenset[str],
) -> bool:
    declared = {
        _text(value).casefold()
        for value in requirement.source_families
        if _text(value)
    }
    return not declared or bool(declared.intersection(allowed))


def _requires_unique_binding(
    requirements: tuple[EvidenceRequirement, ...],
) -> bool:
    """Distinguish one-object grounding from legitimate set-valued evidence."""

    for requirement in requirements:
        cardinality = _text(
            (requirement.metadata or {}).get("selection_cardinality")
        ).casefold()
        if cardinality in {"one", "single", "unique"}:
            return True
        if _text(requirement.evidence_role).casefold() in _UNIQUE_BINDING_ROLES:
            return True
    return False


def _identity_terms(requirement: EvidenceRequirement) -> list[str]:
    """Return producer-declared identity terms without widening to prose."""

    metadata = dict(requirement.metadata or {})
    values = [
        _text(metadata.get(key))
        for key in (
            "mention",
            "normalized_name",
            "entity_name",
            "query_name",
            "source_feature_ref",
        )
        if _text(metadata.get(key))
    ]
    if not values and (
        requirement.kind == "identity"
        or _text(requirement.evidence_role).casefold()
        in _UNIQUE_BINDING_ROLES
    ):
        statement = re.split(
            r"[;；\n]",
            _text(requirement.statement),
            maxsplit=1,
        )[0]
        if "：" in statement:
            statement = statement.rpartition("：")[2]
        elif ":" in statement:
            statement = statement.rpartition(":")[2]
        if _text(statement):
            values.append(_text(statement))
    return list(dict.fromkeys(values))[:8]


def _current_world_port(context: Any) -> Any:
    """Return the only world-model capability allowed to V2 reads."""
    current_port = getattr(context, "current_world", None)
    if current_port is None:
        current_port = getattr(
            getattr(context, "ports", None),
            "current_world",
            None,
        )
    return current_port


def _match(feature: Any, requirement: EvidenceRequirement) -> bool:
    attrs = getattr(feature, "raw_attributes", {}) or {}
    haystack = " ".join(
        [_text(getattr(feature, "source_feature_ref", "")), *(_text(value) for value in attrs.values())]
    ).casefold()
    statement = _text(requirement.statement).casefold()
    scopes = {item.casefold() for item in requirement.scope}
    kind = _text(getattr(feature, "geometry_kind", "unknown")).casefold()
    if kind in {"", "unknown"}:
        geometry = getattr(feature, "geometry", None) or {}
        geometry_type = _text(geometry.get("type") if isinstance(geometry, dict) else "").casefold()
        kind = {
            "point": "point",
            "multipoint": "point",
            "linestring": "line",
            "multilinestring": "line",
            "polygon": "polygon",
            "multipolygon": "polygon",
        }.get(geometry_type, kind)
    if scopes:
        scope_tokens = {
            "road": ("road", "道路", "line"),
            "roads": ("road", "道路", "line"),
            "route": ("road", "道路", "line"),
            "routes": ("road", "道路", "line"),
            "facility": ("facility", "设施", "point"),
            "facilities": ("facility", "设施", "point"),
            "place": ("place", "地点", "point", "poi"),
            "places": ("place", "地点", "point", "poi"),
            "location": ("place", "地点", "point", "poi"),
            "water": ("water", "水", "river", "polygon"),
            "waters": ("water", "水", "river", "polygon"),
            "parcel": ("parcel", "地块", "polygon"),
            "parcels": ("parcel", "地块", "polygon"),
        }
        # Unknown dimension/scope names must not become accidental literal
        # field filters.  Their semantic meaning may be supplied later by a
        # closed-set Cognition decision; until then retrieval is project-wide.
        relevant = [token for scope in scopes for token in scope_tokens.get(scope, ())]
        if relevant and not any(token in haystack or token in kind for token in relevant):
            return False
    # A name/identifier in the requirement is a strong filter.  Generic
    # spatial requirements remain project-wide and therefore return all
    # current source records within the bounded page.
    explicit = [value.casefold() for value in _identity_terms(requirement)]
    if explicit:
        return any(token in haystack for token in explicit)
    # Free-form requirement statements are not source identifiers.  Chinese
    # text in particular has no reliable whitespace tokenization, and a whole
    # sentence such as “交通现状与设施” must not eliminate every valid line or
    # point before World Model/Cognition has interpreted its semantics.  Scope
    # and explicit metadata above are the only deterministic filters here;
    # semantic narrowing belongs to the closed-set cognition decision.
    return True


def _external_query(
    requirements: tuple[EvidenceRequirement, ...],
) -> str:
    """Build a bounded name query without treating whole prose as an ID."""

    values: list[str] = []
    for requirement in requirements:
        for value in _identity_terms(requirement):
            if value and value not in values:
                values.append(value)
        if len(values) >= 8:
            break
    return "、".join(values[:8])


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _external_observation_rows(
    facts: Iterable[EvidenceFact],
) -> list[dict[str, Any]]:
    """Flatten advisory facts into coordinate-bearing spatial support rows."""

    rows: list[dict[str, Any]] = []
    for fact in facts:
        if _text(getattr(fact, "fact_type", "")) != "external_map_observation":
            continue
        fields = dict(getattr(fact, "fields", {}) or {})
        if _text(fields.get("coordinate_trust_status")) not in {
            "verified_direct",
            "verified_transformed",
        }:
            continue
        if _text(fields.get("spatial_evidence_role")) != "feature_location":
            continue
        location = _json_value(fields.get("location_wgs84"))
        if not isinstance(location, (list, tuple)) or len(location) != 2:
            continue
        try:
            lon, lat = float(location[0]), float(location[1])
        except (TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon)
            and math.isfinite(lat)
            and -180.0 <= lon <= 180.0
            and -90.0 <= lat <= 90.0
        ):
            continue
        refs = [
            _text(value)
            for value in (getattr(fact, "spatial_refs", None) or [])
            if _text(value).startswith("external-observation:")
            and not _text(value).startswith("external-observation:external-observation:")
        ]
        if not refs:
            continue
        aliases = _json_value(fields.get("aliases"))
        rows.append({
            "observation_ref": refs[0],
            "location_wgs84": (lon, lat),
            "observed_name": _text(fields.get("observed_name")),
            "aliases": [
                _text(value)
                for value in (aliases if isinstance(aliases, list) else [])
                if _text(value)
            ],
            "observed_type": _text(fields.get("observed_type")),
            "cluster_id": _text(fields.get("cluster_id")),
        })
    return rows


def _feature_kind(feature: Any) -> str:
    kind = _text(getattr(feature, "geometry_kind", "unknown")).casefold()
    if kind not in {"point", "line", "polygon", "multipatch"}:
        geometry = getattr(feature, "normalized_geometry", None) or {}
        kind = {
            "point": "point",
            "multipoint": "point",
            "linestring": "line",
            "multilinestring": "line",
            "polygon": "polygon",
            "multipolygon": "polygon",
        }.get(_text(geometry.get("type")).casefold(), "unknown")
    return kind


def _semantic_family(value: Any) -> str:
    text = _text(value).casefold()
    families = {
        "road": ("road", "street", "highway", "道路", "公路", "街", "路"),
        "water": ("water", "river", "canal", "lake", "河", "沟", "渠", "水"),
        "facility": ("facility", "school", "hospital", "service", "设施", "学校", "医院"),
        "place": ("place", "village", "settlement", "地点", "村", "社区"),
        "parcel": ("parcel", "land", "地块", "用地"),
    }
    for family, tokens in families.items():
        if any(token in text for token in tokens):
            return family
    return ""


def _support_type_compatible(
    observation: dict[str, Any],
    feature: Any,
    entity_rows: list[dict[str, Any]],
) -> bool:
    family = _semantic_family(observation.get("observed_type"))
    if not family:
        return True
    kind = _feature_kind(feature)
    entity_family = _semantic_family(" ".join(
        _text(value)
        for row in entity_rows
        for value in (row.get("concept_types", ()) or ())
    ))
    if entity_family:
        return entity_family == family
    allowed_kinds = {
        "road": {"line"},
        "water": {"line", "polygon"},
        "facility": {"point", "polygon"},
        "place": {"point", "polygon"},
        "parcel": {"polygon"},
    }
    return kind in allowed_kinds.get(family, {kind})


def _distance_m(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    radius = 6_371_000.0
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.asin(min(1.0, math.sqrt(value)))


def _local_spatial_index(
    context: Any,
    snapshot: Any,
    features: list[Any],
    representations_by_feature: dict[tuple[str, str], list[Any]],
) -> tuple[Any, list[tuple[Any, tuple[str, str], Any]]]:
    token = (
        _text(getattr(snapshot, "digest", "")),
        len(features),
        len(representations_by_feature),
    )
    cached = getattr(context, "_v2_external_support_spatial_index", None)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == token:
        return cached[1], cached[2]
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    entries: list[tuple[Any, tuple[str, str], Any]] = []
    geometries: list[Any] = []
    for feature in features:
        source_key = (
            _text(getattr(feature, "dataset_ref", "")),
            _text(getattr(feature, "source_feature_ref", "")),
        )
        if source_key not in representations_by_feature:
            continue
        if not any(
            is_wgs84_equivalent_crs(
                getattr(item, "normalized_crs", "")
                or getattr(item, "crs", "")
            )
            for item in representations_by_feature[source_key]
        ):
            continue
        geometry = getattr(feature, "normalized_geometry", None)
        if not isinstance(geometry, dict):
            continue
        try:
            candidate = shape(geometry)
        except (TypeError, ValueError):
            continue
        if candidate.is_empty or not candidate.is_valid:
            continue
        entries.append((feature, source_key, candidate))
        geometries.append(candidate)
    tree = STRtree(geometries)
    setattr(
        context,
        "_v2_external_support_spatial_index",
        (token, tree, entries),
    )
    return tree, entries


def _external_spatial_support(
    context: Any,
    snapshot: Any,
    features: list[Any],
    representations_by_feature: dict[tuple[str, str], list[Any]],
    kg_entities_by_feature: dict[tuple[str, str], list[dict[str, Any]]],
    observations: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Block provider points against local DATA geometry without binding it."""

    if not observations:
        return {}
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    tree, entries = _local_spatial_index(
        context,
        snapshot,
        features,
        representations_by_feature,
    )
    provisional: dict[
        tuple[str, str],
        dict[str, dict[str, Any]],
    ] = {}
    # 150 m is only a blocking radius.  Exact type-specific thresholds below
    # determine whether the observation supports a local candidate.
    search_degrees = 150.0 / 90_000.0
    thresholds = {"point": 120.0, "line": 80.0, "polygon": 60.0, "multipatch": 60.0}
    for observation in observations:
        location = observation["location_wgs84"]
        point = Point(location)
        for index in tree.query(point.buffer(search_degrees)):
            feature, source_key, geometry = entries[int(index)]
            entity_rows = kg_entities_by_feature.get(source_key, [])
            if not _support_type_compatible(observation, feature, entity_rows):
                continue
            nearest = nearest_points(point, geometry)[1]
            distance = _distance_m(location, (float(nearest.x), float(nearest.y)))
            threshold = thresholds.get(_feature_kind(feature), 60.0)
            if distance > threshold:
                continue
            score = max(0.0, min(1.0, 1.0 - distance / threshold))
            score = 0.55 + score * 0.4
            labels = {
                _text(row.get("canonical_name"))
                for row in entity_rows
                if _text(row.get("canonical_name"))
            }
            labels.update(
                _text(value)
                for row in entity_rows
                for value in (row.get("aliases", ()) or ())
                if _text(value)
            )
            observed_labels = {
                _text(observation.get("observed_name")),
                *(
                    _text(value)
                    for value in (observation.get("aliases", ()) or ())
                    if _text(value)
                ),
            }
            normalized_labels = {"".join(value.split()).casefold() for value in labels}
            normalized_observed = {
                "".join(value.split()).casefold()
                for value in observed_labels
                if value
            }
            if normalized_labels.intersection(normalized_observed):
                score = min(1.0, score + 0.05)
            cluster_id = _text(observation.get("cluster_id"))
            observation_ref = _text(observation.get("observation_ref"))
            cluster_key = cluster_id or observation_ref
            if not cluster_key:
                continue
            row = provisional.setdefault(source_key, {}).setdefault(cluster_key, {
                "cluster_key": cluster_key,
                "score": 0.0,
                "distance_m": distance,
                "observation_refs": [],
                "cluster_ids": [],
                "semantic_match": False,
            })
            row["score"] = max(float(row["score"]), score)
            row["distance_m"] = min(float(row["distance_m"]), distance)
            row["semantic_match"] = bool(
                row["semantic_match"]
                or normalized_labels.intersection(normalized_observed)
            )
            if observation_ref and observation_ref not in row["observation_refs"]:
                row["observation_refs"].append(observation_ref)
            if cluster_id and cluster_id not in row["cluster_ids"]:
                row["cluster_ids"].append(cluster_id)
    candidates_by_cluster: dict[
        str,
        list[tuple[tuple[str, str], dict[str, Any]]],
    ] = {}
    for source_key, cluster_rows in provisional.items():
        for row in cluster_rows.values():
            candidates_by_cluster.setdefault(row["cluster_key"], []).append(
                (source_key, row)
            )
    retained_by_source: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = {}
    for candidates in candidates_by_cluster.values():
        semantic_candidates = [
            item for item in candidates if item[1]["semantic_match"]
        ]
        pool = semantic_candidates or candidates
        ordered = sorted(
            pool,
            key=lambda item: (
                -float(item[1]["score"]),
                float(item[1]["distance_m"]),
                item[0],
            ),
        )[:_EXTERNAL_CANDIDATES_PER_CLUSTER]
        for source_key, row in ordered:
            retained_by_source.setdefault(source_key, []).append(row)
    support: dict[tuple[str, str], dict[str, Any]] = {}
    for source_key, rows in retained_by_source.items():
        semantic_rows = [row for row in rows if row["semantic_match"]]
        selected = semantic_rows or rows
        support[source_key] = {
            "score": max(float(row["score"]) for row in selected),
            "distance_m": min(float(row["distance_m"]) for row in selected),
            "observation_refs": list(dict.fromkeys(
                ref
                for row in selected
                for ref in row["observation_refs"]
            )),
            "cluster_ids": list(dict.fromkeys(
                cluster_id
                for row in selected
                for cluster_id in row["cluster_ids"]
            )),
            "cluster_count": len(selected),
            "nearby_cluster_count": len(rows),
            "semantic_match": bool(semantic_rows),
        }
    return support


def _kg_entities_by_feature(
    context: Any,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index KG entities by source feature without loading source geometry.

    A DATA feature is not itself a WorldEntity.  Keeping this explicit index
    lets Evidence carry both identities: the source feature/resource used for
    later geometry resolution and the KG entity resolved by cognition.  The
    index is deliberately built from the read port, so it works for the V2
    store and for the migration adapter without exposing RDF to callers.
    """

    port = _current_world_port(context)
    finder = getattr(port, "find_entities", None)
    if not callable(finder):
        return {}
    world_model = getattr(context, "world_model", None)
    if _text(getattr(context, "world_model_mode", "")).casefold() == "shadow":
        world_model = getattr(context, "world_model_shadow", None) or world_model
    snapshot = getattr(
        getattr(context, "data_resource_catalog", None),
        "snapshot",
        None,
    )
    cache_token = (
        id(port),
        _text(getattr(snapshot, "digest", "")),
        int(getattr(world_model, "version", 0) or 0),
        _text(getattr(world_model, "snapshot_digest", "")),
    )
    cached = getattr(context, "_v2_evidence_entities_by_feature", None)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and cached[0] == cache_token
    ):
        return cached[1]
    try:
        entities = finder(limit=10000) or []
    except Exception:
        return {}
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_ref = _text(entity.get("entity_ref"))
        if not entity_ref:
            continue
        for part in entity.get("parts", ()) or ():
            if not isinstance(part, dict):
                continue
            source_ref = _text(part.get("source_feature_ref"))
            dataset_ref = _text(part.get("dataset_ref"))
            if not source_ref:
                continue
            row = {
                "entity_ref": entity_ref,
                "entity_identity": _text(entity.get("entity_identity")),
                "canonical_name": _text(entity.get("canonical_name")),
                "aliases": [
                    _text(value)
                    for value in (entity.get("aliases", ()) or ())
                    if _text(value)
                ],
                "concept_types": [
                    _text(value)
                    for value in (entity.get("concept_types", ()) or ())
                    if _text(value)
                ],
                "entity_part_ref": _text(part.get("entity_part_ref")),
                "source_feature_ref": source_ref,
                "dataset_ref": dataset_ref,
            }
            by_source.setdefault((dataset_ref, source_ref), []).append(row)
    for source_key, rows in by_source.items():
        by_source[source_key] = sorted(
            rows,
            key=lambda item: (
                item["entity_ref"],
                item["entity_part_ref"],
            ),
        )
    setattr(
        context,
        "_v2_evidence_entities_by_feature",
        (cache_token, by_source),
    )
    return by_source


def _candidate_identity_projection(
    matched: Iterable[Any],
    kg_entities_by_feature: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Count WorldEntity identities independently from source features.

    A road entity may be represented by many line segments, while one place
    may have a locator point plus several footprint polygons.  Those are
    multiple feature candidates but one identity candidate.  Features that
    Cognition has not linked to a WorldEntity remain separate fallback groups
    and therefore cannot make an identity request look resolved.
    """

    group_keys: set[str] = set()
    entity_refs: set[str] = set()
    entity_backed_features = 0
    fallback_features = 0
    for feature in matched:
        source_key = (
            _text(getattr(feature, "dataset_ref", "")),
            _text(getattr(feature, "source_feature_ref", "")),
        )
        feature_entity_refs = {
            _text(row.get("entity_ref"))
            for row in kg_entities_by_feature.get(source_key, ())
            if _text(row.get("entity_ref"))
        }
        if feature_entity_refs:
            entity_backed_features += 1
            entity_refs.update(feature_entity_refs)
            group_keys.update(
                f"entity:{entity_ref}"
                for entity_ref in feature_entity_refs
            )
            continue
        fallback_features += 1
        group_keys.add(f"source:{source_key[0]}:{source_key[1]}")
    if not group_keys:
        mode = "none"
    elif entity_backed_features and fallback_features:
        mode = "mixed"
    elif entity_backed_features:
        mode = "world_entity"
    else:
        mode = "source_feature"
    return {
        "group_keys": sorted(group_keys),
        "group_count": len(group_keys),
        "entity_refs": sorted(entity_refs),
        "mode": mode,
        "entity_backed_feature_count": entity_backed_features,
        "fallback_feature_count": fallback_features,
    }


def _kg_feature_refs(
    context: Any,
    requirements: tuple[EvidenceRequirement, ...],
) -> set[tuple[str, str]]:
    """Resolve semantic names/types through the World Model without loading geometry."""

    port = _current_world_port(context)
    finder = getattr(port, "find_entities", None)
    if not callable(finder):
        return set()
    refs: set[tuple[str, str]] = set()
    for requirement in requirements:
        metadata = dict(requirement.metadata or {})
        terms = _identity_terms(requirement)
        entity_types = [
            _text(metadata.get(key))
            for key in ("entity_type", "concept_type")
            if _text(metadata.get(key))
        ]
        queries = [("name", term) for term in terms] + [
            ("entity_type", term) for term in entity_types
        ]
        for key, value in queries[:16]:
            try:
                entities = finder(**{key: value, "limit": 32}) or []
            except Exception:
                continue
            for entity in entities:
                for part in entity.get("parts", ()) if isinstance(entity, dict) else ():
                    source_ref = _text(part.get("source_feature_ref")) if isinstance(part, dict) else ""
                    if source_ref:
                        refs.add((_text(part.get("dataset_ref")), source_ref))
    return refs


def retrieve_catalog_evidence(
    context: Any,
    requirements: Iterable[EvidenceRequirement],
    *,
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> ExplorationResult:
    catalog = getattr(context, "data_catalog", None) or getattr(
        context, "data_resource_catalog", None
    )
    snapshot = getattr(catalog, "snapshot", None)
    if snapshot is not None:
        from app.data.admission import assert_current_world_catalog

        assert_current_world_catalog(snapshot)
    features = list(getattr(snapshot, "features", ()) or ())
    requirements = tuple(requirements)
    local_requirements = tuple(
        item for item in requirements if _allows_source(item, _LOCAL_SOURCE_FAMILIES)
    )
    external_requirements = tuple(
        item for item in requirements if _allows_source(item, _EXTERNAL_SOURCE_FAMILIES)
    )
    representation_cache_token = (
        _text(getattr(snapshot, "digest", "")),
        _text(getattr(snapshot, "snapshot_id", "")),
    )
    representation_cache = getattr(
        context,
        "_v2_evidence_representations_by_feature",
        None,
    )
    if (
        isinstance(representation_cache, tuple)
        and len(representation_cache) == 2
        and representation_cache[0] == representation_cache_token
    ):
        representations_by_feature = representation_cache[1]
    else:
        representations_by_feature: dict[tuple[str, str], list[Any]] = {}
        for representation in getattr(snapshot, "representations", ()) or ():
            source_ref = _text(getattr(representation, "source_feature_ref", ""))
            dataset_ref = _text(getattr(representation, "dataset_ref", ""))
            if (
                source_ref
                and _text(getattr(representation, "status", "")) == "available"
                and _text(getattr(representation, "resource_ref", ""))
                and _text(getattr(representation, "geometry_ref", ""))
                and _text(getattr(representation, "source_snapshot_ref", ""))
                == _text(getattr(snapshot, "snapshot_id", ""))
                and _text(getattr(representation, "content_digest", ""))
                and _text(getattr(representation, "geometry_kind", ""))
                in {"point", "line", "polygon", "multipatch"}
            ):
                representations_by_feature.setdefault(
                    (dataset_ref, source_ref), []
                ).append(representation)
        setattr(
            context,
            "_v2_evidence_representations_by_feature",
            (representation_cache_token, representations_by_feature),
        )
    kg_entities_by_feature = _kg_entities_by_feature(context)
    kg_feature_refs = _kg_feature_refs(context, local_requirements)
    # External coordinates are consumed here as advisory blocking evidence.
    # They may add/rank a local DATA candidate, but never become its resource
    # or representation.  The resulting ambiguity is intentionally preserved
    # for Cognition/GROUND to decide in a closed set.
    external_facts: list[EvidenceFact] = []
    external_sources: list[EvidenceSource] = []
    external_trace: dict[str, Any] = {}
    if external_requirements:
        try:
            from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
                retrieve_from_cached_map,
            )

            external_facts, external_sources, external_trace = retrieve_from_cached_map(
                context,
                query=_external_query(external_requirements),
                entity_scope=sorted({
                    scope
                    for item in external_requirements
                    for scope in item.scope
                }),
                limit=min(64, max(8, int(candidate_limit) * 4)),
            )
        except Exception as exc:
            external_facts, external_sources = [], []
            external_trace = {
                "status": "failed",
                "cache_only": True,
                "error_type": type(exc).__name__,
            }
    else:
        external_trace = {
            "status": "skipped_by_source_policy",
            "cache_only": True,
        }
    external_rows = _external_observation_rows(external_facts)
    external_support = _external_spatial_support(
        context,
        snapshot,
        features,
        representations_by_feature,
        kg_entities_by_feature,
        external_rows,
    )
    matched: list[Any] = []
    locally_supported_keys: set[tuple[str, str]] = set()
    for feature in features:
        source_ref = _text(getattr(feature, "source_feature_ref", ""))
        dataset_ref = _text(getattr(feature, "dataset_ref", ""))
        source_key = (dataset_ref, source_ref)
        if source_key not in representations_by_feature:
            continue
        local_match = source_key in kg_feature_refs or any(
            _match(feature, requirement) for requirement in local_requirements
        )
        if local_match:
            locally_supported_keys.add(source_key)
        if local_match or source_key in external_support:
            matched.append(feature)
    matched = sorted(matched, key=lambda item: (
        -float(external_support.get((
            _text(getattr(item, "dataset_ref", "")),
            _text(getattr(item, "source_feature_ref", "")),
        ), {}).get("score", 0.0)),
        _text(getattr(item, "dataset_ref", "")),
        _text(getattr(item, "source_feature_ref", "")),
    ))
    total = len(matched)
    page = matched[max(0, int(candidate_offset)): max(0, int(candidate_offset)) + max(1, int(candidate_limit))]
    candidate_refs: list[FeatureEvidenceRef] = []
    facts: list[EvidenceFact] = []
    source_refs: list[str] = []
    for feature in page:
        source_id = _text(getattr(feature, "source_feature_ref", ""))
        dataset = _text(getattr(feature, "dataset_ref", ""))
        source_key = (dataset, source_id)
        support = external_support.get(source_key, {})
        representations = representations_by_feature.get(source_key, [])
        primary_representation = representations[0]
        resource_ref = _text(getattr(primary_representation, "resource_ref", ""))
        geometry_ref = _text(getattr(primary_representation, "geometry_ref", ""))
        normalized_crs = _text(getattr(primary_representation, "crs", ""))
        source_ref = f"data:{dataset}:{source_id}"
        source_refs.append(source_ref)
        identity = SourceFeatureIdentity(
            source_feature_id=source_id,
            source_dataset_ref=dataset,
            source_layer=_text(getattr(feature, "layer_ref", "")),
            source_snapshot_digest=_text(getattr(snapshot, "digest", "")),
            geometry_digest=_text(getattr(feature, "source_feature_digest", "")),
            crs=normalized_crs,
            source_crs=_text(getattr(feature, "source_crs", "")),
            normalized_crs=normalized_crs,
            source_snapshot_ref=_text(getattr(snapshot, "snapshot_id", "")),
        )
        entity_rows = kg_entities_by_feature.get(source_key, [])
        entity_refs = sorted({
            _text(row.get("entity_ref"))
            for row in entity_rows
            if _text(row.get("entity_ref"))
        })
        # Preserve the resolved KG label/type in the identity projection when
        # available.  DATA remains the source of truth for raw attributes;
        # these values are cognition results and are therefore optional.
        primary_entity = entity_rows[0] if entity_rows else {}
        identity.canonical_name = _text(primary_entity.get("canonical_name"))
        identity.aliases = sorted({
            _text(value)
            for row in entity_rows
            for value in (row.get("aliases", ()) or ())
            if _text(value)
        })
        identity.entity_type = _text(
            (primary_entity.get("concept_types", ()) or [""])[0]
            if primary_entity.get("concept_types")
            else ""
        )
        representation_refs = [
            _text(getattr(item, "representation_ref", ""))
            for item in representations
            if _text(getattr(item, "representation_ref", ""))
        ]
        support_score = float(support.get("score", 0.0) or 0.0)
        support_refs = [
            _text(value)
            for value in (support.get("observation_refs", ()) or ())
            if _text(value)
        ]
        candidate_refs.append(FeatureEvidenceRef(
            identity=identity,
            entity_refs=entity_refs,
            geometry_ref=geometry_ref,
            resource_ref=resource_ref,
            representation_refs=representation_refs,
            source_snapshot_ref=_text(getattr(snapshot, "snapshot_id", "")),
            normalized_crs=normalized_crs,
            geometry_authority="data_resource_catalog",
            provenance_refs=[source_ref, *support_refs],
            selection_evidence=(
                {
                    "external_nearest_distance_m": round(
                        float(support.get("distance_m", 0.0) or 0.0),
                        3,
                    ),
                    "external_support_cluster_count": float(
                        support.get("cluster_count", 0) or 0
                    ),
                    "external_nearby_cluster_count": float(
                        support.get("nearby_cluster_count", 0) or 0
                    ),
                    "external_semantic_match": (
                        1.0 if support.get("semantic_match") else 0.0
                    ),
                }
                if support_refs
                else {}
            ),
            source_authority_score=0.8,
            spatial_support_score=support_score,
            external_support_score=support_score,
            retrieval_score=min(0.95, 0.8 + 0.15 * support_score),
        ))
        attrs = getattr(feature, "raw_attributes", {}) or {}
        fact_fields = {
            str(key): _text(value)
            for key, value in attrs.items()
            if value not in (None, "")
        }
        if support_refs:
            fact_fields.update({
                "external_support_refs": json.dumps(
                    support_refs,
                    ensure_ascii=False,
                ),
                "external_support_cluster_ids": json.dumps(
                    support.get("cluster_ids", []) or [],
                    ensure_ascii=False,
                ),
                "external_nearest_distance_m": str(
                    round(float(support.get("distance_m", 0.0) or 0.0), 3)
                ),
                "external_support_cluster_count": str(
                    int(support.get("cluster_count", 0) or 0)
                ),
                "external_nearby_cluster_count": str(
                    int(support.get("nearby_cluster_count", 0) or 0)
                ),
                "external_semantic_match": str(
                    bool(support.get("semantic_match"))
                ).lower(),
            })
        facts.append(EvidenceFact(
            statement=f"DATA source feature {source_id} is available",
            confidence=0.8,
            source_refs=[source_ref],
            spatial_refs=[resource_ref],
            fact_type="source_feature_identity",
            fields=fact_fields,
            status="verified",
            evidence_role="world_model_source",
            source_kind="data_resource_catalog",
            spatial_granularity=_text(getattr(feature, "geometry_kind", "unknown")),
        ))
    unique_binding = _requires_unique_binding(requirements)
    matched_keys = {
        (
            _text(getattr(feature, "dataset_ref", "")),
            _text(getattr(feature, "source_feature_ref", "")),
        )
        for feature in matched
    }
    external_identity_ambiguous = any(
        source_key in matched_keys
        and
        source_key not in locally_supported_keys
        and (
            int(support.get("cluster_count", 0) or 0) != 1
            or not bool(support.get("semantic_match"))
        )
        for source_key, support in external_support.items()
    )
    identity_projection = _candidate_identity_projection(
        matched,
        kg_entities_by_feature,
    )
    unique_world_entity = bool(
        identity_projection["group_count"] == 1
        and len(identity_projection["entity_refs"]) == 1
        and identity_projection["mode"] == "world_entity"
    )
    bounded_set_complete = bool(
        total > 0
        and max(0, int(candidate_offset)) == 0
        and total <= max(1, int(candidate_limit))
    )
    requirement_resolved = bool(
        total > 0
        and (
            unique_world_entity and not external_identity_ambiguous
            if unique_binding
            else bounded_set_complete
        )
    )
    status = (
        "resolved"
        if requirement_resolved
        else "multiple"
        if identity_projection["group_count"] > 1 or external_identity_ambiguous
        else "unresolved"
    )
    world_model = _current_world_port(context)
    packet = EvidencePacket(
        request="; ".join(_text(item.statement) for item in requirements),
        bundle_snapshot_digest="",
        data_snapshot_ref=_text(getattr(snapshot, "snapshot_id", "")),
        data_snapshot_digest=_text(getattr(snapshot, "digest", "")),
        world_model_snapshot_ref=_text(getattr(world_model, "snapshot_ref", "")),
        world_model_snapshot_digest=_text(
            getattr(world_model, "snapshot_digest", "")
        ),
        kg_version=_text(getattr(context, "kg_version", "")),
        l1_snapshot_ref=_text(getattr(context, "l1_snapshot_ref", "")),
        candidate_refs=candidate_refs,
        candidate_total=total,
        candidate_identity_total=identity_projection["group_count"],
        candidate_entity_refs=identity_projection["entity_refs"][:64],
        identity_grouping=identity_projection["mode"],
        candidate_offset=max(0, int(candidate_offset)),
        candidate_limit=max(1, int(candidate_limit)),
        candidates_truncated=total > len(page),
        next_candidate_offset=(max(0, int(candidate_offset)) + len(page) if total > max(0, int(candidate_offset)) + len(page) else None),
        ambiguity_status=status,
        sufficiency=("sufficient" if requirement_resolved else "partial" if total else "insufficient"),
        missing_evidence=(
            []
            if requirement_resolved
            else [item.requirement_id for item in requirements]
        ),
        external_refs=[
            ref
            for fact in external_facts
            for ref in fact.spatial_refs
            if _text(ref)
        ],
        query_trace=[
            {
                "step": "v2_data_world_model_retrieval",
                "source_snapshot_ref": _text(getattr(snapshot, "snapshot_id", "")),
                "candidate_total": total,
                "candidate_identity_total": identity_projection["group_count"],
                "candidate_entity_ref_count": len(
                    identity_projection["entity_refs"]
                ),
                "identity_grouping": identity_projection["mode"],
                "entity_backed_feature_count": identity_projection[
                    "entity_backed_feature_count"
                ],
                "fallback_feature_count": identity_projection[
                    "fallback_feature_count"
                ],
                "external_cache": external_trace,
                "external_observation_count": len(external_rows),
                "external_spatial_candidate_count": len(external_support),
                "external_candidates_per_cluster_limit": (
                    _EXTERNAL_CANDIDATES_PER_CLUSTER
                ),
                "external_identity_ambiguous": external_identity_ambiguous,
                "external_geometry_authority": "advisory_only",
            }
        ],
    )
    bundle = EvidenceBundle(
        request=packet.request,
        facts=[*facts, *external_facts],
        sources=[
            EvidenceSource(
                source_type="gis_layer",
                reference=ref,
                evidence_role="world_model_source",
                authority="source",
                snapshot_ref=_text(getattr(snapshot, "snapshot_id", "")),
            )
            for ref in source_refs
        ] + external_sources,
        confidence=0.8 if facts else (0.65 if external_facts else 0.0),
        # Advisory map observations can support a name/position claim but do
        # not resolve a requirement for a local executable feature.
        unresolved=(
            []
            if requirement_resolved
            else [item.requirement_id for item in requirements]
        ),
    )
    return ExplorationResult(
        evidence_bundle=bundle,
        evidence_packet=packet,
        spatial_cognition=SpatialCognitionEvidence(kg_confidence=0.8 if facts else 0.0),
    )


__all__ = ["retrieve_catalog_evidence"]
