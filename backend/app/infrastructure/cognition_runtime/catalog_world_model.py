"""Legacy read adapter backed directly by a normalized DATA catalog.

Kept for migration callers that have no context/runtime graph.  Production
``v2_only`` contexts use ``world_model_store.WorldModelKGStore``: the same DATA
projection is materialized as an RDF KG before ports are injected.  New code
should not instantiate this adapter directly.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _identity(feature: Any) -> str:
    attributes = dict(getattr(feature, "raw_attributes", {}) or {})
    for key in (
        "entity_ref",
        "physical_entity_ref",
        "road_ref",
        "place_ref",
        "parent_ref",
        "entity_id",
        "physical_id",
    ):
        value = attributes.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ":".join(
        str(value)
        for value in (
            getattr(feature, "dataset_ref", ""),
            getattr(feature, "source_feature_ref", ""),
            getattr(feature, "source_feature_digest", ""),
        )
    )


def _entity_ref(identity: str) -> str:
    digest = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()[:24]
    return f"entity:{digest}"


class CatalogWorldModelAdapter:
    """Expose DATA source records as unresolved world-model candidates."""

    def __init__(self, catalog: Any):
        snapshot = getattr(catalog, "snapshot", catalog)
        self._features = tuple(getattr(snapshot, "features", ()) or ())
        self._representations = tuple(getattr(snapshot, "representations", ()) or ())
        self.snapshot_ref = str(getattr(snapshot, "snapshot_id", "") or "")
        self.snapshot_digest = str(getattr(snapshot, "digest", "") or "")

    def find_entities(
        self,
        *,
        identity: str = "",
        source_feature_ref: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        wanted_identity = str(identity or "")
        wanted_feature = str(source_feature_ref or "")
        grouped: dict[str, list[Any]] = {}
        for feature in self._features:
            source_ref = str(getattr(feature, "source_feature_ref", "") or "")
            feature_identity = _identity(feature)
            if wanted_feature and source_ref != wanted_feature:
                continue
            if wanted_identity and feature_identity != wanted_identity:
                continue
            grouped.setdefault(feature_identity, []).append(feature)

        result: list[dict[str, Any]] = []
        for feature_identity, features in sorted(grouped.items()):
            parts = [
                {
                    "entity_part_ref": f"part:{feature_identity}:{getattr(feature, 'source_feature_ref', '')}",
                    "source_feature_ref": str(getattr(feature, "source_feature_ref", "") or ""),
                    "dataset_ref": str(getattr(feature, "dataset_ref", "") or ""),
                    "layer_ref": str(getattr(feature, "layer_ref", "") or ""),
                    "geometry_kind": str(getattr(feature, "geometry_kind", "unknown") or "unknown"),
                }
                for feature in features
            ]
            result.append(
                {
                    "entity_ref": _entity_ref(feature_identity),
                    "entity_identity": feature_identity,
                    "status": "unresolved",
                    "parts": parts,
                    "source_snapshot_ref": self.snapshot_ref,
                }
            )
            if len(result) >= max(1, int(limit)):
                break
        return result

    def representations_for(self, entity_ref: str, *, limit: int = 50) -> list[dict[str, Any]]:
        wanted = str(entity_ref or "")
        result: list[dict[str, Any]] = []
        for representation in self._representations:
            source_feature_ref = str(getattr(representation, "source_feature_ref", "") or "")
            feature = next(
                (item for item in self._features if str(getattr(item, "source_feature_ref", "") or "") == source_feature_ref),
                None,
            )
            if feature is None or _entity_ref(_identity(feature)) != wanted:
                continue
            result.append(
                {
                    "representation_ref": str(getattr(representation, "representation_ref", "") or ""),
                    "resource_ref": str(getattr(representation, "resource_ref", "") or ""),
                    "purpose": str(getattr(representation, "purpose", "") or ""),
                    "geometry_kind": str(getattr(representation, "geometry_kind", "unknown") or "unknown"),
                    "crs": str(getattr(representation, "crs", "") or ""),
                    "content_digest": str(getattr(representation, "content_digest", "") or ""),
                    "source_snapshot_ref": str(getattr(representation, "source_snapshot_ref", "") or self.snapshot_ref),
                }
            )
            if len(result) >= max(1, int(limit)):
                break
        return result

    def build_network_retry_adapter(self) -> Any:
        """No legacy RDF retry adapter exists in a catalog-only session."""

        return None


__all__ = ["CatalogWorldModelAdapter"]
