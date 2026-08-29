"""Evidence projection for normalized, locally cached map observations.

The records in this module are advisory observations.  They can bind a name
or approximate location to a planning concept, but they never become Bundle
features or executable geometry.  In particular this module performs no HTTP
or provider SDK calls.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)

RETRIEVER_VERSION = "external-map-cache-v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _terms(value: str) -> list[str]:
    raw = _text(value).casefold()
    if not raw:
        return []
    # Preserve Chinese names as whole strings while also allowing whitespace /
    # punctuation-separated aliases to match a provider's normalized name.
    parts = [item for item in re.split(r"[\s,，、;；|/]+", raw) if item]
    return list(dict.fromkeys([raw, *parts]))


def _scope_matches(observation: ExternalObservation, entity_scope: Iterable[str]) -> bool:
    requested = " ".join(_text(item).casefold() for item in entity_scope)
    if not requested:
        return True
    observed = " ".join(
        [
            _text(observation.observed_type),
            _text(observation.metadata.get("role")),
            _text(observation.metadata.get("category")),
        ]
    ).casefold()
    groups = {
        "road": ("road", "street", "highway", "道路", "公路", "街"),
        "water": ("water", "river", "canal", "lake", "河", "沟", "渠", "水"),
        "facility": ("facility", "school", "hospital", "service", "设施", "学校", "医院"),
        "place": ("place", "village", "settlement", "地点", "村", "社区"),
    }
    for key, tokens in groups.items():
        if key in requested or any(token in requested for token in tokens):
            return any(token in observed for token in tokens)
    return True


def _matches(observation: ExternalObservation, query: str) -> bool:
    terms = _terms(query)
    if not terms:
        return True
    values = [
        observation.observed_name,
        *observation.aliases,
        observation.observed_type,
        observation.query_name,
        observation.scope_bucket,
        *[_text(value) for value in observation.metadata.values()],
    ]
    haystack = " ".join(value for value in values if value).casefold()
    return any(term in haystack for term in terms)


def _json(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _fact_and_source(
    observation: ExternalObservation,
    snapshot: ExternalObservationSnapshot,
) -> tuple[EvidenceFact, EvidenceSource]:
    ref = f"external-observation:{observation.observation_id}"
    location = observation.location_wgs84 or observation.location_native
    source_refs = [
        value
        for value in (observation.raw_response_ref, observation.source_record_ref)
        if _text(value)
    ]
    fields = {
        "observation_id": observation.observation_id,
        "provider": observation.provider,
        "stage": observation.stage,
        "operation": observation.operation,
        "scope_bucket": observation.scope_bucket,
        "observed_name": observation.observed_name,
        "aliases": _json(observation.aliases),
        "observed_type": observation.observed_type,
        "location_wgs84": _json(observation.location_wgs84),
        "coordinate_contract": observation.coordinate_contract,
        "geometry_semantics": observation.geometry_semantics,
        "cluster_id": observation.cluster_id,
    }
    if location:
        fields["location"] = _json(location)
    if observation.metadata:
        fields["metadata"] = _json(observation.metadata)
    label = observation.observed_name or observation.observed_type or "未命名地图观察"
    statement = (
        f"{observation.provider} 缓存观察到 {label}"
        f"（{observation.scope_bucket}，{observation.geometry_semantics}）；"
        "该记录仅用于名称/位置线索绑定，最终几何必须回指数据层资源。"
    )
    fact = EvidenceFact(
        statement=statement,
        confidence=0.65 if observation.status.startswith("success") else 0.35,
        source_refs=source_refs,
        spatial_refs=[ref],
        fact_type="external_map_observation",
        fields={key: value for key, value in fields.items() if value != ""},
        source_locator=ref,
        support_relation="cached_provider_observation",
        support_relations=["name_observation", "coordinate_observation"],
        status="verified" if observation.status.startswith("success") else "needs_review",
        evidence_role="location_binding",
        source_kind="external_map_cache",
        spatial_granularity=observation.geometry_semantics or "point_observation",
        planning_use="grounding",
    )
    source = EvidenceSource(
        source_type="external",
        reference=f"external-map-cache:{observation.provider}:{observation.stage}:{observation.observation_id}",
        confidence=fact.confidence,
        evidence_role="location_binding",
        authority="advisory",
        availability="available" if observation.attempted else "not_attempted",
        supports=["name", "alias", "coordinate_observation"],
        snapshot_ref=snapshot.snapshot_id,
    )
    return fact, source


def retrieve_from_cached_map(
    context: Any,
    query: str = "",
    entity_scope: Iterable[str] = (),
    limit: int = 32,
) -> tuple[list[EvidenceFact], list[EvidenceSource], dict[str, Any]]:
    """Return matching observations from a hydrated PlanningContext snapshot."""

    snapshot = getattr(context, "external_observation_snapshot", None)
    if not isinstance(snapshot, ExternalObservationSnapshot):
        return [], [], {
            "retriever": RETRIEVER_VERSION,
            "status": "unavailable",
            "cache_only": True,
            "matched_count": 0,
        }
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    for observation in snapshot.observations:
        if not _scope_matches(observation, entity_scope) or not _matches(observation, query):
            continue
        fact, source = _fact_and_source(observation, snapshot)
        facts.append(fact)
        sources.append(source)
        if len(facts) >= max(1, int(limit)):
            break
    return facts, sources, {
        "retriever": RETRIEVER_VERSION,
        "status": "returned" if facts else "empty",
        "cache_only": True,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_digest": snapshot.digest,
        "provider_count": len({item.provider for item in snapshot.observations}),
        "matched_count": len(facts),
        "excluded_count": sum(snapshot.excluded_counts.values()),
    }


__all__ = ["RETRIEVER_VERSION", "retrieve_from_cached_map"]
