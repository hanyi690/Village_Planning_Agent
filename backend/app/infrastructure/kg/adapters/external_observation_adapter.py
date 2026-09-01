"""Project cached provider observations into KG support assertions.

The adapter deliberately creates support nodes rather than asserting that a
provider row is a ``Road``, ``Parcel`` or other executable world entity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from rdflib import Graph, Literal, RDF

from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
    is_wgs84_equivalent_crs,
)
from app.data.catalog.external_observation_cache import cluster_external_observations
from app.infrastructure.kg.ontology import PLN


@dataclass(frozen=True)
class ExternalEntitySupport:
    cluster_id: str
    observation_refs: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    centroid_wgs84: tuple[float, float] | None = None
    trust_statuses: tuple[str, ...] = ()


def _canonical_ref(observation_id: str) -> str:
    prefix = "external-observation:"
    value = str(observation_id or "")
    while value.startswith(prefix + prefix):
        value = value[len(prefix):]
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _spatially_verified(observation: ExternalObservation) -> bool:
    return (
        observation.status == "success_nonempty"
        and observation.attempted
        and observation.location_wgs84 is not None
        and observation.coordinate_trust_status in {"verified_direct", "verified_transformed"}
        and observation.spatial_evidence_role == "feature_location"
        and is_wgs84_equivalent_crs(observation.coordinate_target_crs)
    )


def _cluster_id(observations: Iterable[ExternalObservation]) -> str:
    ids = sorted(item.observation_id for item in observations)
    digest = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]
    return f"external-cluster:{digest}"


def build_external_supports(
    snapshot: ExternalObservationSnapshot,
) -> list[ExternalEntitySupport]:
    cluster_ids = cluster_external_observations(snapshot.observations)
    groups: dict[str, list[ExternalObservation]] = {}
    for observation in snapshot.observations:
        key = cluster_ids.get(observation.observation_id) or _cluster_id([observation])
        groups.setdefault(key, []).append(observation)
    supports: list[ExternalEntitySupport] = []
    for key, items in sorted(groups.items()):
        points = [
            item.location_wgs84
            for item in items
            if _spatially_verified(item) and item.location_wgs84
        ]
        centroid = None
        if points:
            centroid = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
        aliases = {
            alias
            for item in items
            for alias in [item.observed_name, *item.aliases]
            if alias
        }
        roles = {
            role
            for item in items
            for role in [item.observed_type, str(item.metadata.get("role") or "")]
            if role
        }
        supports.append(
            ExternalEntitySupport(
                cluster_id=key,
                observation_refs=tuple(
                    _canonical_ref(item.observation_id) for item in items
                ),
                aliases=tuple(sorted(aliases)),
                roles=tuple(sorted(roles)),
                centroid_wgs84=centroid,
                trust_statuses=tuple(sorted({item.coordinate_trust_status for item in items})),
            )
        )
    return supports


def project_external_observations(
    graph: Graph,
    snapshot: ExternalObservationSnapshot,
) -> list[ExternalEntitySupport]:
    """Add reversible support assertions to ``graph`` and return typed views."""

    supports = build_external_supports(snapshot)
    by_id = {_canonical_ref(item.observation_id): item for item in snapshot.observations}
    for support in supports:
        subject = PLN[support.cluster_id.replace(":", "_")]
        graph.add((subject, RDF.type, PLN.ExternalObservationSupport))
        graph.add((subject, PLN.supportSnapshot, Literal(snapshot.snapshot_id)))
        for alias in support.aliases:
            graph.add((subject, PLN.supportAlias, Literal(alias)))
        for role in support.roles:
            graph.add((subject, PLN.supportRole, Literal(role)))
        for ref in support.observation_refs:
            item = by_id.get(ref)
            if item is not None:
                graph.add((subject, PLN.spatialEvidenceRole, Literal(item.spatial_evidence_role)))
        if support.centroid_wgs84:
            lon, lat = support.centroid_wgs84
            graph.add((subject, PLN.advisoryCentroidLongitude, Literal(lon)))
            graph.add((subject, PLN.advisoryCentroidLatitude, Literal(lat)))
        graph.add(
            (subject, PLN.advisoryCoordinateTrust, Literal(";".join(support.trust_statuses)))
        )
        for ref in support.observation_refs:
            observation = by_id.get(ref)
            observation_node = PLN["observation_" + ref.replace(":", "_")]
            graph.add((subject, PLN.externalObservation, observation_node))
            graph.add((observation_node, PLN.observationRef, Literal(ref)))
            if observation is not None:
                graph.add((observation_node, PLN.provider, Literal(observation.provider)))
                graph.add(
                    (observation_node, PLN.coordinateTrustStatus, Literal(observation.coordinate_trust_status))
                )
                graph.add(
                    (observation_node, PLN.spatialEvidenceRole, Literal(observation.spatial_evidence_role))
                )
                if observation.observed_name:
                    graph.add((observation_node, PLN.observedName, Literal(observation.observed_name)))
                for alias in observation.aliases:
                    graph.add((observation_node, PLN.supportAlias, Literal(alias)))
                if _spatially_verified(observation) and observation.location_wgs84:
                    lon, lat = observation.location_wgs84
                    graph.add((observation_node, PLN.advisoryLongitude, Literal(lon)))
                    graph.add((observation_node, PLN.advisoryLatitude, Literal(lat)))
    return supports


__all__ = [
    "ExternalEntitySupport",
    "build_external_supports",
    "project_external_observations",
]
