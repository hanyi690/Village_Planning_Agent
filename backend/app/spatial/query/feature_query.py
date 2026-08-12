"""Typed feature queries over a SpatialWorkspace returning SpatialFeature lists."""

from __future__ import annotations

from typing import Any, Mapping

from app.data.model.base import SpatialFeature
from app.spatial.model.workspace import SpatialWorkspace

BBoxTuple = tuple[float, float, float, float]


def _feature_geometry(item: Any) -> dict[str, Any] | None:
    if isinstance(item, Mapping):
        return dict(item.get("geometry") or {})
    geometry = getattr(item, "geometry", None)
    return dict(geometry) if isinstance(geometry, Mapping) else None


def _feature_value(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        properties = item.get("properties") or {}
        return properties.get(name, item.get(name))
    return getattr(item, name, None)


def _match_filters(item: Any, filters: Mapping[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        actual = _feature_value(item, key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


def _feature_in_bbox(item: Any, bbox: BBoxTuple) -> bool:
    geometry = _feature_geometry(item)
    if not geometry:
        return False
    try:
        from shapely.geometry import box, shape

        return shape(geometry).intersects(box(*bbox))
    except Exception:
        return False


class FeatureQuery:
    def __init__(self, workspace: SpatialWorkspace) -> None:
        self.workspace = workspace

    def _items_for_layer(self, layer: str) -> list[Any]:
        results: list[Any] = []
        for group in (self.workspace.points, self.workspace.lines, self.workspace.polygons):
            results.extend(group.get(layer) or [])
        return results

    def layers(self) -> list[str]:
        names: set[str] = set()
        for group in (self.workspace.points, self.workspace.lines, self.workspace.polygons):
            names.update((group or {}).keys())
        return sorted(names)

    def by_layer(
        self,
        layer: str,
        *,
        bbox: BBoxTuple | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[SpatialFeature]:
        features: list[SpatialFeature] = []
        for item in self._items_for_layer(layer):
            if bbox is not None and not _feature_in_bbox(item, bbox):
                continue
            if not _match_filters(item, filters):
                continue
            geometry = _feature_geometry(item)
            if not geometry:
                continue
            features.append(
                SpatialFeature.model_validate({
                    "geometry": geometry,
                    "bsm": str(_feature_value(item, "bsm") or ""),
                    "ysdm": str(_feature_value(item, "ysdm") or ""),
                    "layer_type": layer,
                })
            )
        return features


def query_workspace(
    workspace: SpatialWorkspace,
    layer: str,
    *,
    bbox: BBoxTuple | None = None,
    filters: Mapping[str, Any] | None = None,
) -> list[SpatialFeature]:
    return FeatureQuery(workspace).by_layer(layer, bbox=bbox, filters=filters)


__all__ = ["BBoxTuple", "FeatureQuery", "query_workspace"]
