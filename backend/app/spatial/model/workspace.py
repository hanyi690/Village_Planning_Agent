"""Read-only spatial workspace over the normalized DATA catalog."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.data.model.snapshot import SessionDataSnapshot


def _current_world_catalog(catalog: Any) -> Any:
    snapshot = getattr(catalog, "snapshot", catalog)
    if snapshot is None:
        raise ValueError("SpatialWorkspace requires a normalized catalog")
    from app.data.admission import assert_current_world_catalog, current_world_snapshot
    from app.data.resource_catalog import DataResourceCatalog

    if isinstance(catalog, DataResourceCatalog):
        assert_current_world_catalog(snapshot)
        return catalog
    current = current_world_snapshot(snapshot)
    assert_current_world_catalog(current)
    return DataResourceCatalog(current)


def _representation_kind(feature: Any) -> str:
    """Return the normalized kind used for executable spatial views."""

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


class SpatialWorkspace:
    """DATA-only query surface passed to WM/GROUND/EXECUTE.

    The workspace has no bundle constructor, no planned-output merge, and no
    geometry mutation API.  Feature-layer views are computed from generic
    ``SourceFeature`` descriptors only for callers that still need a simple
    read-only ``group.get(layer)`` query shape.
    """

    def __init__(self, snapshot: SessionDataSnapshot, *, catalog: Any) -> None:
        if catalog is None:
            raise ValueError("SpatialWorkspace requires a normalized catalog")
        self.snapshot = snapshot
        self._catalog = _current_world_catalog(catalog)

    @classmethod
    def from_data_catalog(
        cls,
        catalog: Any,
        *,
        session_id: str,
        village_name: str = "",
        source: str = "data_catalog",
    ) -> "SpatialWorkspace":
        admitted = _current_world_catalog(catalog)
        snapshot = SessionDataSnapshot.from_data_catalog(
            admitted,
            session_id=session_id,
            village_name=village_name,
            source=source,
        )
        return cls(snapshot, catalog=admitted)

    @property
    def village_name(self) -> str:
        return str(self.snapshot.village_name or "")

    @property
    def metadata(self) -> Any:
        crs = self.source_crs
        return type("DataMetadata", (), {"crs": crs})()

    @property
    def source_crs(self) -> str:
        for collection in self.snapshot.collections:
            value = str(getattr(collection, "crs", "") or "").strip()
            if value and value.casefold() not in {"unknown", "none", "null"}:
                return value
        return "EPSG:4326"

    @property
    def input_document_refs(self) -> list[dict[str, Any]]:
        return []

    @property
    def report_refs(self) -> list[dict[str, Any]]:
        return []

    def _features(self) -> list[Any]:
        return list(getattr(self._catalog.snapshot, "features", ()) or ())

    def _layer_views(self) -> tuple[dict[str, list[Any]], dict[str, list[Any]], dict[str, list[Any]]]:
        groups = (defaultdict(list), defaultdict(list), defaultdict(list))
        for feature in self._features():
            kind = _representation_kind(feature)
            index = {"point": 0, "line": 1, "polygon": 2}.get(kind)
            if index is None:
                continue
            layer = str(getattr(feature, "layer_ref", "") or "")
            groups[index][layer].append(feature)
        return groups

    @property
    def points(self) -> dict[str, list[Any]]:
        return dict(self._layer_views()[0])

    @property
    def lines(self) -> dict[str, list[Any]]:
        return dict(self._layer_views()[1])

    @property
    def polygons(self) -> dict[str, list[Any]]:
        return dict(self._layer_views()[2])

    @property
    def rasters(self) -> Any:
        return type("DataRasters", (), {"all_rasters": {}})()

    @property
    def tables(self) -> Any:
        return type("DataTables", (), {"all_tables": {}})()

    def current_parcels(self) -> list[Any]:
        return list(self.polygons.get("landuse_current") or [])

    def iter_source_features(self) -> list[Any]:
        return self._features()

    def query_resources(
        self,
        *,
        geometry_kind: str = "",
        layer_ref: str = "",
        attributes: dict[str, Any] | None = None,
        limit: int = 256,
    ) -> list[Any]:
        wanted_kind = str(geometry_kind or "").casefold()
        wanted_layer = str(layer_ref or "").casefold()
        wanted_attributes = attributes or {}
        result: list[Any] = []
        for feature in self._features():
            if wanted_kind and _representation_kind(feature) != wanted_kind:
                continue
            if wanted_layer and wanted_layer not in str(getattr(feature, "layer_ref", "") or "").casefold():
                continue
            raw = getattr(feature, "raw_attributes", {}) or {}
            if any(str(raw.get(key, "")) != str(value) for key, value in wanted_attributes.items()):
                continue
            result.append(feature)
            if len(result) >= max(1, int(limit)):
                break
        return result

    def to_resource_catalog(self, *, snapshot_id: str = "") -> Any:
        return self._catalog

    def attach_resource_catalog(self, catalog: Any) -> None:
        self._catalog = _current_world_catalog(catalog)

    def to_delivery_inputs(self) -> dict[str, Any]:
        features = []
        for feature in self._features():
            geometry = getattr(feature, "normalized_geometry", None) or getattr(feature, "geometry", None)
            if geometry is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    **dict(getattr(feature, "raw_attributes", {}) or {}),
                    "source_feature_ref": str(getattr(feature, "source_feature_ref", "") or ""),
                    "source_dataset_ref": str(getattr(feature, "dataset_ref", "") or ""),
                    "source_layer_ref": str(getattr(feature, "layer_ref", "") or ""),
                    "source_crs": str(getattr(feature, "source_crs", "") or ""),
                },
            })
        if not features:
            raise ValueError("SpatialWorkspace has no materializable source features")
        return {"data_catalog_geojson": {"type": "FeatureCollection", "features": features}}


__all__ = ["SpatialWorkspace"]
