"""Selective spatial reads with a GeoJSON fallback for local artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.modules.schema.contracts.spatial_delivery_contracts import (
    DeliverySpatialSnapshot,
    FeatureBatch,
    SpatialLayerRef,
    SpatialReadRequest,
)


class SpatialDataPort(Protocol):
    def describe(self, ref: SpatialLayerRef) -> SpatialLayerRef: ...
    def read(self, request: SpatialReadRequest) -> FeatureBatch: ...
    def read_by_bsms(self, ref: SpatialLayerRef, bsms: list[str], columns: list[str]) -> FeatureBatch: ...
    def materialize(self, ref: SpatialLayerRef) -> FeatureBatch: ...


class GeoJSONSpatialDataPort:
    """Deterministic local adapter; filters before returning feature payloads."""

    def describe(self, ref: SpatialLayerRef) -> SpatialLayerRef:
        payload = json.loads(Path(ref.path).read_text(encoding="utf-8"))
        features = payload.get("features", [])
        fields = sorted({key for feature in features for key in feature.get("properties", {})})
        return ref.model_copy(update={"fields": fields, "feature_count": len(features)})

    def read(self, request: SpatialReadRequest) -> FeatureBatch:
        payload = json.loads(Path(request.layer_ref.path).read_text(encoding="utf-8"))
        selected = set(request.columns)
        wanted = set(request.bsms)
        features = []
        for feature in payload.get("features", []):
            properties = feature.get("properties", {})
            if wanted and str(properties.get("BSM", properties.get("bsm", ""))) not in wanted:
                continue
            if selected:
                properties = {key: value for key, value in properties.items() if key in selected}
            item = {"type": "Feature", "properties": properties}
            if request.read_geometry:
                item["geometry"] = feature.get("geometry")
            features.append(item)
        return FeatureBatch(
            layer_ref=request.layer_ref,
            features=features,
            selected_columns=sorted(selected),
            complete=False,
        )

    def read_by_bsms(self, ref: SpatialLayerRef, bsms: list[str], columns: list[str]) -> FeatureBatch:
        return self.read(SpatialReadRequest(layer_ref=ref, bsms=bsms, columns=columns))

    def materialize(self, ref: SpatialLayerRef) -> FeatureBatch:
        return self.read(SpatialReadRequest(layer_ref=ref, read_geometry=True))


__all__ = ["SpatialDataPort", "GeoJSONSpatialDataPort", "DeliverySpatialSnapshot"]
