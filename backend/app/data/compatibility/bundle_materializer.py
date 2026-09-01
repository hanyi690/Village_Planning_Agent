"""Materialize a traceable legacy GeoJSON view from DATA + World Model.

This adapter is intentionally one-way.  It never turns a legacy layer key or
BSM into a WorldEntity and is not used by the V2 authoritative read path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _value(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def materialize_world_model_geojson(
    world_model: Any,
    catalog: Any,
    *,
    layer_profile: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return GeoJSON layers for legacy consumers with explicit lineage.

    ``layer_profile`` is an output mapping only (source layer → legacy key).
    Without it all features are emitted under ``source_features_geojson``.
    Missing geometry is diagnosed by omission from the layer rather than being
    replaced with a centroid or an external observation coordinate.
    """

    snapshot = getattr(catalog, "snapshot", None)
    features = list(getattr(snapshot, "features", ()) or ())
    world_digest = str(getattr(world_model, "snapshot_digest", "") or "")
    source_snapshot_digest = str(getattr(snapshot, "digest", "") or "")
    profile = {str(key): str(value) for key, value in (layer_profile or {}).items()}
    layers: dict[str, dict[str, Any]] = {}
    for feature in features:
        geometry = _value(feature, "geometry", None)
        if not isinstance(geometry, Mapping):
            continue
        source_ref = str(_value(feature, "source_feature_ref", "") or "").strip()
        if not source_ref:
            continue
        try:
            entities = world_model.find_entities(source_feature_ref=source_ref, limit=16)
        except Exception:
            entities = []
        entity_refs = sorted(
            {
                str(_value(item, "entity_ref", "") or "").strip()
                for item in (entities or ())
                if str(_value(item, "entity_ref", "") or "").strip()
            }
        )
        representation_refs: list[str] = []
        for entity_ref in entity_refs:
            try:
                representations = world_model.representations_for(entity_ref, limit=32)
            except Exception:
                representations = []
            representation_refs.extend(
                str(_value(item, "representation_ref", "") or "").strip()
                for item in (representations or ())
                if str(_value(item, "representation_ref", "") or "").strip()
            )
        layer_key = profile.get(str(_value(feature, "layer_ref", "") or ""), "source_features_geojson")
        output = layers.setdefault(
            layer_key,
            {"type": "FeatureCollection", "features": []},
        )
        properties = {
            "source_feature_ref": source_ref,
            "source_dataset_ref": str(_value(feature, "dataset_ref", "") or ""),
            "source_snapshot_digest": source_snapshot_digest,
            "source_feature_digest": str(_value(feature, "source_feature_digest", "") or ""),
            "entity_refs": sorted(set(entity_refs)),
            "representation_refs": sorted(set(representation_refs)),
            "world_model_digest": world_digest,
            "id_scope": "delivery",
        }
        output["features"].append({
            "type": "Feature",
            "id": f"delivery:{source_ref}",
            "properties": properties,
            "geometry": dict(geometry),
        })
    return layers


__all__ = ["materialize_world_model_geojson"]
