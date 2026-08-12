"""Delivery and map-layer projections from explicit immutable artifacts."""

from __future__ import annotations

import hashlib
import json

from app.application.projections.models import (
    DeliveryView,
    MapLayerCollectionView,
    MapLayerView,
)
from app.application.projections.session import ProjectionNotFoundError
from app.application.queries.artifacts import artifact_queries
from app.application.queries.workflow_state import load_workflow_state


def _layer_view(layer: dict[str, object]) -> MapLayerView:
    layer_name = str(layer.get("layerType") or layer.get("layer_type") or "")
    data = layer.get("data") or layer.get("geojson") or {
        "type": "FeatureCollection",
        "features": [],
    }
    if not isinstance(data, dict):
        data = {"type": "FeatureCollection", "features": []}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if layer_name in {"current_landuse", "current_road", "boundary"}:
        kind = "current"
    elif layer_name == "input_constraint":
        kind = "constraint"
    elif layer_name == "complete_planned_landuse":
        kind = "planned"
    else:
        kind = "overlay"
    features = data.get("features")
    return MapLayerView(
        layer_type=kind,
        layer_name=layer_name,
        checksum=hashlib.sha256(raw).hexdigest(),
        feature_count=len(features) if isinstance(features, list) else 0,
        geojson=data,
    )


class DeliveryProjectionService:
    async def get(self, session_id: str) -> DeliveryView:
        if not await load_workflow_state(session_id):
            raise ProjectionNotFoundError("session not found")
        manifest = await artifact_queries.read(session_id, "delivery_manifest")
        if not manifest or not isinstance(manifest.payload, dict):
            return DeliveryView(session_id=session_id, available=False)
        payload = manifest.payload
        deliverables = [
            item for item in payload.get("deliverables") or [] if isinstance(item, dict)
        ]
        return DeliveryView(
            session_id=session_id,
            available=True,
            delivery_status=(
                str(payload.get("delivery_status"))
                if payload.get("delivery_status") else None
            ),
            statutory_complete=bool(payload.get("statutory_complete")),
            snapshot_checksum=str(manifest.artifact_ref.get("digest") or ""),
            deferral_summary=dict(payload.get("deferral_summary") or {}),
            diagnostic_summary=dict(payload.get("diagnostic_summary") or {}),
            deliverables=deliverables,
            downloads=[str(item.get("path")) for item in deliverables if item.get("path")],
        )

    async def map_layers(self, session_id: str) -> MapLayerCollectionView:
        snapshot = await artifact_queries.read(session_id, "delivery_spatial_snapshot")
        if not snapshot or not isinstance(snapshot.payload, dict):
            raise ProjectionNotFoundError("delivery spatial snapshot not found")
        render_layers = await artifact_queries.read(session_id, "render_layers")
        if not render_layers or not isinstance(render_layers.payload, list):
            raise ProjectionNotFoundError("delivery render layers not found")
        layers = [
            _layer_view(layer)
            for layer in render_layers.payload
            if isinstance(layer, dict)
        ]
        return MapLayerCollectionView(
            session_id=session_id,
            snapshot_checksum=str(snapshot.artifact_ref.get("digest") or ""),
            delivery_status=(
                str(snapshot.payload.get("delivery_status"))
                if snapshot.payload.get("delivery_status") else None
            ),
            layers=layers,
        )


delivery_projections = DeliveryProjectionService()


__all__ = ["DeliveryProjectionService", "delivery_projections"]
