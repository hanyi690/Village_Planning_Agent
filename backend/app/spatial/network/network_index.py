"""Thin typed wrapper over deterministic road-network helpers."""

from __future__ import annotations

from typing import Any

from app.spatial.network.schemas import (
    NetworkBuildConfig,
    NetworkBuildResult,
    RoadEdgeRecord,
    RoadNodeRecord,
)

from app.spatial.model.workspace import SpatialWorkspace


def _feature_geojson(road: Any) -> dict[str, Any]:
    if isinstance(road, dict):
        return dict(road)
    properties: dict[str, Any] = {}
    for key in ("bsm", "road_name", "road_level", "name"):
        value = getattr(road, key, None)
        if value not in (None, ""):
            properties[key] = value
    geometry = getattr(road, "geometry", None) or {}
    return {"type": "Feature", "properties": properties, "geometry": geometry}


class NetworkIndex:
    def __init__(self, workspace: SpatialWorkspace | None = None) -> None:
        self.workspace = workspace
        self._result: NetworkBuildResult | None = None

    def _road_source(self) -> dict[str, Any]:
        if self.workspace is None:
            raise ValueError("NetworkIndex requires a workspace to build from roads")
        roads = list(self.workspace.lines.get("roads_current") or [])
        if not roads:
            raise ValueError("workspace has no roads_current layer")
        return {
            "type": "FeatureCollection",
            "features": [_feature_geojson(road) for road in roads],
        }

    def build(self, output_dir: str | Any, config: NetworkBuildConfig | None = None) -> NetworkBuildResult:
        from app.spatial.network.network_builder import RoadNetworkBuilder

        builder = RoadNetworkBuilder(config)
        self._result = builder.build(self._road_source(), output_dir)
        return self._result

    @property
    def result(self) -> NetworkBuildResult | None:
        return self._result

    @property
    def metrics(self) -> dict[str, Any]:
        if self._result is None:
            return {}
        return dict(self._result.report.get("selected_topology") or {})


def build_network_from_workspace(
    workspace: SpatialWorkspace,
    output_dir: str | Any,
    config: NetworkBuildConfig | None = None,
) -> NetworkBuildResult:
    return NetworkIndex(workspace).build(output_dir, config=config)


__all__ = [
    "NetworkBuildConfig",
    "NetworkBuildResult",
    "NetworkIndex",
    "RoadEdgeRecord",
    "RoadNodeRecord",
    "build_network_from_workspace",
]
