"""Immutable data manifest owned by the data layer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _canonical_payload_from_geojson(payloads: dict[str, Any]) -> dict[str, Any]:
    """Adapt the tiny GeoJSON bundle protocol used by lightweight callers."""

    payload: dict[str, Any] = {
        "points": {},
        "lines": {},
        "polygons": {},
    }
    targets = {
        "boundary_geojson": ("polygons", "admin_areas"),
        "landuse_current_geojson": ("polygons", "landuse_current"),
        "landuse_planned_geojson": ("polygons", "landuse_planned"),
        "road_geojson": ("lines", "roads_current"),
        "planned_road_geojson": ("lines", "roads_planned"),
        "external_road_geojson": ("lines", "external_roads"),
        "water_line_geojson": ("lines", "water_lines"),
        "water_geojson": ("polygons", "water_bodies"),
        "annotation_geojson": ("points", "annotations_current"),
    }
    for output_key, value in (payloads or {}).items():
        if not str(output_key).endswith("_geojson") or not isinstance(value, dict):
            continue
        group, key = targets.get(
            str(output_key),
            ("polygons", str(output_key).removesuffix("_geojson")),
        )
        features = []
        for feature in value.get("features") or []:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            features.append({
                "geometry": feature.get("geometry", {}),
                **(dict(properties) if isinstance(properties, dict) else {}),
            })
        if features:
            payload[group][key] = features
    return payload


class CollectionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    media_type: str = "application/geo+json"
    crs: str = "EPSG:4326"
    feature_count: int = 0
    digest: str
    source: str = ""
    source_uris: tuple[str, ...] = ()
    source_feature_ids: tuple[str, ...] = ()
    source_feature_count: int = 0
    source_feature_digest: str = ""


class SessionDataSnapshot(BaseModel):
    """Frozen inventory of session inputs; it never embeds feature payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    session_id: str
    village_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collections: tuple[CollectionSnapshot, ...] = ()
    source_refs: tuple[str, ...] = ()
    digest: str

    @classmethod
    def from_bundle(
        cls,
        bundle: Any,
        *,
        session_id: str,
        source: str = "data_catalog",
    ) -> "SessionDataSnapshot":
        if bundle is None:
            raise ValueError("SessionDataSnapshot requires a data-layer bundle")

        # Use the canonical persisted representation as the single source for
        # both BundleStore serialization and the source manifest.  The old
        # path called ``to_geojson_dict`` here after BundleStore had already
        # called ``to_bundle_dict``; for a large village that retained two
        # complete geometry trees during every layer checkpoint.
        from app.data.model.canonical import to_bundle_dict

        try:
            payload = to_bundle_dict(bundle)
        except (AttributeError, TypeError, ValueError):
            # Keep the small protocol used by cache/key tests: callers may
            # provide a lightweight object exposing only to_geojson_dict.
            if not hasattr(bundle, "to_geojson_dict"):
                raise ValueError("SessionDataSnapshot requires a data-layer bundle")
            payload = _canonical_payload_from_geojson(bundle.to_geojson_dict())
        return cls.from_canonical_payload(
            payload,
            session_id=session_id,
            village_name=str(getattr(bundle, "village_name", "") or ""),
            source=source,
        )

    @classmethod
    def from_canonical_payload(
        cls,
        payload: dict[str, Any],
        *,
        session_id: str,
        village_name: str = "",
        source: str = "data_catalog",
    ) -> "SessionDataSnapshot":
        """Build a manifest from one already serialized Bundle payload.

        ``BundleStore.serialize`` passes its canonical payload here so a
        checkpoint never materializes a second full GeoJSON bundle merely to
        compute source digests.  The collection names and feature projection
        intentionally mirror ``VillageBundle.to_geojson_dict``.
        """

        points = payload.get("points") or {}
        lines = payload.get("lines") or {}
        polygons = payload.get("polygons") or {}

        def _features(group: dict[str, Any], key: str) -> list[dict[str, Any]]:
            values = group.get(key) or []
            return [value for value in values if isinstance(value, dict)]

        collection_features: dict[str, list[dict[str, Any]]] = {}
        for key in ("admin_areas", "planning_scope"):
            values = _features(polygons, key)
            if values:
                collection_features["boundary_geojson"] = values[:1]
                break
        for key in ("landuse_current", "landuse_planned"):
            values = _features(polygons, key)
            if values:
                collection_features[f"{key}_geojson"] = values
        for output_key, input_keys in {
            "road_geojson": ("roads_current",),
            "planned_road_geojson": ("roads_planned",),
            "external_road_geojson": ("external_roads",),
            "water_line_geojson": ("water_lines",),
            "annotation_geojson": ("annotations_current", "annotations_planned"),
        }.items():
            values = [
                feature
                for input_key in input_keys
                for feature in _features(
                    lines if "road" in output_key or "water_line" in output_key else points,
                    input_key,
                )
            ]
            if values:
                collection_features[output_key] = values
        water = _features(polygons, "water_bodies")
        if water:
            collection_features["water_geojson"] = water
        for key in polygons:
            if key in {"admin_areas", "planning_scope", "landuse_current", "landuse_planned", "water_bodies"}:
                continue
            values = _features(polygons, key)
            if values:
                collection_features[f"{key}_geojson"] = values

        collections: list[CollectionSnapshot] = []
        for key, raw_features in sorted(collection_features.items()):
            # Hash the exact FeatureCollection JSON shape incrementally.  The
            # previous implementation built a second full feature tree for
            # every collection solely to compute this digest.
            canonical_hasher = hashlib.sha256()
            canonical_hasher.update(b'{"features":[')
            source_features: list[dict[str, str]] = []
            source_uris: set[str] = set()
            source_feature_ids: list[str] = []
            for index, raw_feature in enumerate(raw_features):
                feature = {
                    "type": "Feature",
                    "geometry": raw_feature.get("geometry", {}),
                    "properties": {
                        item_key: item_value
                        for item_key, item_value in raw_feature.items()
                        if item_key != "geometry"
                    },
                }
                if index:
                    canonical_hasher.update(b",")
                canonical_hasher.update(
                    json.dumps(
                        feature,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                properties = feature["properties"]
                raw = properties.get("_raw") if isinstance(properties, dict) else None
                raw = raw if isinstance(raw, dict) else properties
                source_feature_id = str(
                    raw.get("source_feature_id") or ""
                ).strip() if isinstance(raw, dict) else ""
                if not source_feature_id:
                    continue
                source_features.append({
                    "index": str(index),
                    "source_feature_id": source_feature_id,
                    "source_uri": str(
                        raw.get("source_uri") or ""
                    ).strip() if isinstance(raw, dict) else "",
                    "source_content_digest": str(
                        raw.get("source_content_digest") or ""
                    ).strip() if isinstance(raw, dict) else "",
                    "source_geometry_digest": str(
                        raw.get("source_geometry_digest") or ""
                    ).strip() if isinstance(raw, dict) else "",
                })
                source_feature_ids.append(source_feature_id)
                source_uri = str(raw.get("source_uri") or "").strip() if isinstance(raw, dict) else ""
                if source_uri:
                    source_uris.add(source_uri)
            canonical_hasher.update(b'],"type":"FeatureCollection"}')
            source_feature_digest = ""
            if source_features:
                source_feature_digest = "sha256:" + hashlib.sha256(
                    json.dumps(
                        source_features,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            collections.append(
                CollectionSnapshot(
                    key=str(key),
                    crs="EPSG:4326",
                    feature_count=len(raw_features),
                    digest="sha256:" + canonical_hasher.hexdigest(),
                    source=source,
                    source_uris=tuple(sorted(source_uris)),
                    source_feature_ids=tuple(source_feature_ids),
                    source_feature_count=len(source_features),
                    source_feature_digest=source_feature_digest,
                )
            )
        manifest = [item.model_dump(mode="json") for item in collections]
        digest = "sha256:" + hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot_id = f"data-{session_id}-{digest.removeprefix('sha256:')[:16]}"
        return cls(
            snapshot_id=snapshot_id,
            session_id=session_id,
            village_name=village_name,
            collections=tuple(collections),
            source_refs=tuple(
                dict.fromkeys(
                    [source]
                    + [uri for item in collections for uri in item.source_uris]
                )
            ),
            digest=digest,
        )

    def collection(self, key: str) -> CollectionSnapshot | None:
        return next((item for item in self.collections if item.key == key), None)


__all__ = ["CollectionSnapshot", "SessionDataSnapshot"]
