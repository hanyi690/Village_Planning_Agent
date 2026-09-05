"""Evidence retriever backed exclusively by the immutable DATA catalog."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource

RETRIEVER_VERSION = "data-catalog-v1"
_FEATURE_LIMIT = 12
_SEARCH_INDEX_CACHE: OrderedDict[str, tuple[tuple[Any, str], ...]] = OrderedDict()
_SEARCH_INDEX_CACHE_LOCK = RLock()
_SEARCH_INDEX_CACHE_LIMIT = 8


def _query_matches(feature: Any, query: str) -> bool:
    text = str(query or "").strip().casefold()
    if not text:
        return True
    attrs = getattr(feature, "raw_attributes", {}) or {}
    values = [getattr(feature, "source_feature_ref", ""), getattr(feature, "layer_ref", "")]
    values.extend(str(value) for value in attrs.values() if value not in (None, "", [], {}))
    return text in " ".join(str(value).casefold() for value in values)


def _search_index(snapshot: Any) -> tuple[tuple[Any, str], ...]:
    """Build one bounded query index for an immutable catalog snapshot."""

    digest = str(getattr(snapshot, "digest", "") or "")
    if digest:
        with _SEARCH_INDEX_CACHE_LOCK:
            cached = _SEARCH_INDEX_CACHE.get(digest)
            if cached is not None:
                _SEARCH_INDEX_CACHE.move_to_end(digest)
                return cached
    index = []
    for feature in snapshot.features:
        attrs = getattr(feature, "raw_attributes", {}) or {}
        values = [
            getattr(feature, "source_feature_ref", ""),
            getattr(feature, "layer_ref", ""),
        ]
        values.extend(
            str(value)
            for value in attrs.values()
            if value not in (None, "", [], {})
        )
        index.append((feature, " ".join(str(value).casefold() for value in values)))
    result = tuple(index)
    if digest:
        with _SEARCH_INDEX_CACHE_LOCK:
            _SEARCH_INDEX_CACHE[digest] = result
            _SEARCH_INDEX_CACHE.move_to_end(digest)
            while len(_SEARCH_INDEX_CACHE) > _SEARCH_INDEX_CACHE_LIMIT:
                _SEARCH_INDEX_CACHE.popitem(last=False)
    return result


async def retrieve_from_data_catalog(
    session_id: str,
    entity_scope: list[str] | None = None,
    query: str = "",
    required_facts: list[str] | None = None,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Return bounded source-feature facts and never geometry bodies."""

    from app.infrastructure.context_runtime.manager import get_cached_context
    from app.data.admission import assert_current_world_catalog

    context = get_cached_context(session_id)
    catalog = getattr(context, "data_resource_catalog", None) if context is not None else None
    snapshot = getattr(catalog, "snapshot", None)
    if snapshot is None:
        return [], []
    assert_current_world_catalog(snapshot)
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    normalized_query = str(query or "").strip().casefold()
    for feature, search_text in _search_index(snapshot):
        if normalized_query and normalized_query not in search_text:
            continue
        attrs = dict(feature.raw_attributes or {})
        label = next(
            (str(value).strip() for key, value in attrs.items() if str(key).casefold() in {"name", "label", "title", "road_name", "facility_name"} and str(value).strip()),
            str(feature.layer_ref or feature.source_feature_ref),
        )
        source_ref = f"data:{feature.dataset_ref}:{feature.source_feature_ref}"
        resource_ref = f"resource:{feature.dataset_ref}:{feature.source_feature_ref}"
        fact = EvidenceFact(
            statement=f"{label} 的 DATA 源要素引用为 {feature.source_feature_ref}",
            confidence=0.8 if feature.validity_status == "valid" else 0.55,
            source_refs=[source_ref],
            spatial_refs=[resource_ref] if feature.geometry is not None else [],
            fact_type="data_source_feature",
            fields={
                "source_feature_ref": feature.source_feature_ref,
                "dataset_ref": feature.dataset_ref,
                "layer_ref": feature.layer_ref,
                "geometry_kind": feature.geometry_kind,
                "normalized_geometry_kind": getattr(
                    feature,
                    "normalized_geometry_kind",
                    "unknown",
                ),
                "source_crs": feature.source_crs,
                "source_snapshot_ref": str(snapshot.snapshot_id or ""),
                "source_feature_digest": feature.source_feature_digest,
                "geometry_authority": "data_resource_catalog",
            },
            evidence_span=f"{label} | {feature.source_feature_ref}",
            source_locator=resource_ref,
            support_relation="data_source_identity",
            status="verified" if feature.validity_status == "valid" else "ambiguous",
            evidence_role="location_binding",
            source_kind="data_resource_catalog",
            spatial_granularity="feature" if feature.geometry is not None else "none",
            planning_use="grounding",
        )
        facts.append(fact)
        sources.append(EvidenceSource(
            source_type="gis_layer",
            reference=source_ref,
            confidence=fact.confidence,
            evidence_role="location_binding",
            authority="authoritative",
            snapshot_ref=str(snapshot.snapshot_id or ""),
        ))
        if len(facts) >= _FEATURE_LIMIT:
            break
    return facts, sources


__all__ = ["RETRIEVER_VERSION", "retrieve_from_data_catalog"]
